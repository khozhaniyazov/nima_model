const API_BASE = "http://localhost:5000";

export interface StatsResponse {
  stats: {
    total_requests: number;
    successful_renders: number;
    avg_quality_score: number | null;
    unique_error_patterns: number;
    success_rate: number;
  };
  quality_dims: {
    avg_layout: number;
    avg_educational: number;
    avg_technical: number;
    avg_pacing: number;
    avg_manim: number;
  };
  quality_tiers: {
    pct_80_plus: number;
    pct_70_79: number;
    pct_60_69: number;
    pct_below_60: number;
  };
  top_domains: Array<{ domain: string; count: number }>;
  top_errors: Array<{
    error_category: string;
    root_cause: string;
    fix_description: string;
    occurrence_count: number;
  }>;
  renders_today: number;
  avg_render_duration: number;
  last_render_at: string;
}

export interface TopExample {
  prompt: string;
  domain: string;
  topic: string;
  overall_score: number;
  visual_quality_score: number;
  educational_value_score: number;
  pacing: number;
  video_path: string;
  created_at: string;
}

export async function fetchStats(): Promise<StatsResponse> {
  try {
    const res = await fetch(`${API_BASE}/stats`);
    if (!res.ok) throw new Error("Failed to fetch stats");
    return await res.json();
  } catch (error) {
    console.error("[API] fetchStats error:", error);
    return {
      stats: {
        total_requests: 0,
        successful_renders: 0,
        avg_quality_score: null,
        unique_error_patterns: 0,
        success_rate: 0,
      },
      quality_dims: {
        avg_layout: 0,
        avg_educational: 0,
        avg_technical: 0,
        avg_pacing: 0,
        avg_manim: 0,
      },
      quality_tiers: {
        pct_80_plus: 0,
        pct_70_79: 0,
        pct_60_69: 0,
        pct_below_60: 0,
      },
      top_domains: [],
      top_errors: [],
      renders_today: 0,
      avg_render_duration: 0,
      last_render_at: "",
    };
  }
}

export async function fetchTopExamples(): Promise<{ top_examples: TopExample[] }> {
  try {
    const res = await fetch(`${API_BASE}/stats/top-examples`);
    if (!res.ok) throw new Error("Failed to fetch top examples");
    return await res.json();
  } catch (error) {
    console.error("[API] fetchTopExamples error:", error);
    return { top_examples: [] };
  }
}

export interface Video {
  id: string;
  render_job_id: string;
  request_id: string;
  filename: string;
  organized_path: string;
  file_size_bytes: number;
  duration_seconds: number | null;
  resolution: string | null;
  domain: string;
  prompt: string;
  cdn_url: string | null;
  created_at: string;
  last_accessed: string | null;
  render_status: string;
  overall_score: number | null;
  visual_quality_score: number | null;
  educational_value_score: number | null;
  pacing: number | null;
  topic?: string;
}

export interface VideoListResponse {
  videos: Video[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface VideoSearchResponse {
  results: Video[];
  query: string;
}

export interface VideoCdnUrlResponse {
  video_id: string;
  url: string;
  source: "stored" | "generated" | "local";
}

export async function fetchVideos(params: {
  page?: number;
  per_page?: number;
  domain?: string;
  sort_by?: "created_at" | "overall_score";
  sort_order?: "asc" | "desc";
} = {}): Promise<VideoListResponse> {
  try {
    const searchParams = new URLSearchParams();
    if (params.page) searchParams.set("page", String(params.page));
    if (params.per_page) searchParams.set("per_page", String(params.per_page));
    if (params.domain) searchParams.set("domain", params.domain);
    if (params.sort_by) searchParams.set("sort_by", params.sort_by);
    if (params.sort_order) searchParams.set("sort_order", params.sort_order);

    const res = await fetch(`${API_BASE}/api/videos?${searchParams}`);
    if (!res.ok) throw new Error("Failed to fetch videos");
    return await res.json();
  } catch (error) {
    console.error("[API] fetchVideos error:", error);
    return { videos: [], total: 0, page: 1, per_page: 20, pages: 0 };
  }
}

export async function searchVideos(query: string, page: number = 1, perPage: number = 20): Promise<VideoSearchResponse> {
  try {
    const searchParams = new URLSearchParams();
    searchParams.set("q", query);
    searchParams.set("page", String(page));
    searchParams.set("per_page", String(perPage));

    const res = await fetch(`${API_BASE}/api/videos/search?${searchParams}`);
    if (!res.ok) throw new Error("Failed to search videos");
    return await res.json();
  } catch (error) {
    console.error("[API] searchVideos error:", error);
    return { results: [], query };
  }
}

export async function getVideoCdnUrl(videoId: string): Promise<VideoCdnUrlResponse> {
  try {
    const res = await fetch(`${API_BASE}/api/videos/cdn-url/${videoId}`);
    if (!res.ok) throw new Error("Failed to get CDN URL");
    return await res.json();
  } catch (error) {
    console.error("[API] getVideoCdnUrl error:", error);
    throw error;
  }
}
