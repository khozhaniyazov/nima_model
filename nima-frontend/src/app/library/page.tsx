"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchVideos, searchVideos, getVideoCdnUrl, type Video, type VideoListResponse } from "@/lib/api";
import { VideoCard } from "@/components/VideoCard";
import VideoPlayer from "@/components/VideoPlayer";

function Corners() {
  return (
    <div className="corners-wrapper">
      <div className="corner-accent corner-tl" />
      <div className="corner-accent corner-tr" />
      <div className="corner-accent corner-bl" />
      <div className="corner-accent corner-br" />
    </div>
  );
}

const API_BASE = "http://localhost:5000";

export default function VideoLibrary() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [pagination, setPagination] = useState({ page: 1, per_page: 20, total: 0, pages: 0 });
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Video[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedDomain, setSelectedDomain] = useState("");
  const [sortBy, setSortBy] = useState<"created_at" | "overall_score">("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [playingVideo, setPlayingVideo] = useState<Video | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const domains = ["math", "physics", "cs", "chemistry", "general"];

  const loadVideos = useCallback(async () => {
    setLoading(true);
    try {
      const response: VideoListResponse = await fetchVideos({
        page: pagination.page,
        per_page: pagination.per_page,
        domain: selectedDomain || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
      });
      setVideos(response.videos);
      setPagination(prev => ({ ...prev, total: response.total, pages: response.pages }));
    } catch (error) {
      console.error("Failed to load videos:", error);
    } finally {
      setLoading(false);
    }
  }, [pagination.page, pagination.per_page, selectedDomain, sortBy, sortOrder]);

  useEffect(() => {
    if (!searchQuery) {
      loadVideos();
    }
  }, [loadVideos, searchQuery]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setIsSearching(true);
    try {
      const response = await searchVideos(searchQuery);
      setSearchResults(response.results);
    } catch (error) {
      console.error("Search failed:", error);
    } finally {
      setIsSearching(false);
    }
  };

  const handlePlay = async (video: Video) => {
    setPlayingVideo(video);
    try {
      const cdnResponse = await getVideoCdnUrl(video.id);
      setVideoUrl(cdnResponse.url);
    } catch {
      setVideoUrl(`${API_BASE}/outputs/${video.filename}`);
    }
  };

  const handlePageChange = (newPage: number) => {
    setPagination(prev => ({ ...prev, page: newPage }));
  };

  const displayedVideos = searchQuery ? searchResults : videos;

  return (
    <>
      <div className="blueprint-grid" />
      <div className="crosshair crosshair-h" />
      <div className="crosshair crosshair-v" />
      <div className="scanline-overlay" />

      <div style={{ position: "relative", zIndex: 10, minHeight: "100vh", padding: "40px" }}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "40px" }}>
          <div style={{ display: "flex", gap: "24px" }}>
            <div style={{ width: "48px", height: "48px", border: "2px solid var(--accent-cyan)", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
              <div style={{ width: "16px", height: "16px", background: "var(--accent-cyan)" }} className="animate-pulse-op" />
            </div>
            <div>
              <h1 className="font-display" style={{ fontSize: "2.5rem", lineHeight: 1, letterSpacing: "-0.02em", color: "var(--text-primary)" }}>
                VIDEO_LIBRARY <span style={{ color: "var(--text-muted)", fontSize: "1.5rem" }}>SYS.V1</span>
              </h1>
              <div style={{ fontSize: "0.75rem", color: "var(--accent-cyan)", marginTop: "8px", letterSpacing: "0.2em" }}>
                [ ASSET_ARCHIVE_ACCESSED ]
              </div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>
            <div>MODE: LIBRARY</div>
            <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ display: "inline-block", width: 8, height: 8, background: loading ? "var(--accent-yellow)" : "var(--accent-green)", border: "1px solid #fff" }} />
              {loading ? "LOADING..." : "ONLINE"}
            </div>
          </div>
        </header>

        <div className="border-box" style={{ marginBottom: "24px" }}>
          <Corners />
          <div style={{ padding: "20px" }}>
            <form onSubmit={handleSearch} style={{ display: "flex", gap: "12px", marginBottom: "16px" }}>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="> SEARCH_PROMPTS..."
                className="technical-input"
                style={{ flex: 1 }}
              />
              <button type="submit" className="btn-brutal" disabled={isSearching}>
                {isSearching ? "[ SEARCHING... ]" : "[ EXECUTE_SEARCH ]"}
              </button>
            </form>

            <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", letterSpacing: "0.1em" }}>DOMAIN:</span>
                <select
                  value={selectedDomain}
                  onChange={(e) => setSelectedDomain(e.target.value)}
                  className="filter-select"
                >
                  <option value="">ALL</option>
                  {domains.map(d => (
                    <option key={d} value={d}>{d.toUpperCase()}</option>
                  ))}
                </select>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", letterSpacing: "0.1em" }}>SORT:</span>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as "created_at" | "overall_score")}
                  className="filter-select"
                >
                  <option value="created_at">DATE</option>
                  <option value="overall_score">QUALITY</option>
                </select>
                <button
                  onClick={() => setSortOrder(o => o === "asc" ? "desc" : "asc")}
                  className="btn-refresh"
                >
                  [{sortOrder === "desc" ? "DESC" : "ASC"}]
                </button>
              </div>

              {searchQuery && (
                <button
                  onClick={() => { setSearchQuery(""); setSearchResults([]); }}
                  className="btn-refresh"
                >
                  [ CLEAR_SEARCH ]
                </button>
              )}
            </div>
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: "80px", color: "var(--text-muted)" }}>
            <div style={{ fontSize: "1.5rem", marginBottom: "16px" }}>◌</div>
            LOADING_ASSETS...
          </div>
        ) : displayedVideos.length === 0 ? (
          <div style={{ textAlign: "center", padding: "80px", color: "var(--text-muted)" }}>
            <div style={{ fontSize: "1.5rem", marginBottom: "16px" }}>○</div>
            {searchQuery ? "NO_RESULTS_FOUND" : "NO_VIDEOS_ARCHIVED"}
          </div>
        ) : (
          <>
            <div style={{ marginBottom: "16px", fontSize: "0.7rem", color: "var(--text-muted)", letterSpacing: "0.1em" }}>
              {searchQuery 
                ? `FOUND: ${searchResults.length} RESULTS`
                : `DISPLAYING: ${videos.length} OF ${pagination.total} ASSETS`
              }
            </div>

            <div className="video-grid">
              {displayedVideos.map(video => (
                <VideoCard key={video.id} video={video} onPlay={handlePlay} />
              ))}
            </div>

            {!searchQuery && pagination.pages > 1 && (
              <div style={{ display: "flex", justifyContent: "center", gap: "8px", marginTop: "32px" }}>
                <button
                  onClick={() => handlePageChange(pagination.page - 1)}
                  disabled={pagination.page <= 1}
                  className="btn-brutal"
                >
                  [ PREV ]
                </button>
                <span style={{ padding: "8px 16px", color: "var(--text-secondary)", fontSize: "0.85rem" }}>
                  PAGE {pagination.page} / {pagination.pages}
                </span>
                <button
                  onClick={() => handlePageChange(pagination.page + 1)}
                  disabled={pagination.page >= pagination.pages}
                  className="btn-brutal"
                >
                  [ NEXT ]
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {playingVideo && videoUrl && (
        <div 
          className="video-modal"
          onClick={() => setPlayingVideo(null)}
        >
          <div className="video-modal-content" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ color: "var(--text-primary)", fontSize: "1rem", margin: 0 }}>
                {playingVideo.prompt.length > 60 ? `${playingVideo.prompt.substring(0, 60)}...` : playingVideo.prompt}
              </h3>
              <button
                onClick={() => setPlayingVideo(null)}
                style={{ 
                  background: "none", 
                  border: "none", 
                  color: "var(--text-secondary)", 
                  fontSize: "1.5rem", 
                  cursor: "pointer" 
                }}
              >
                ×
              </button>
            </div>
            <VideoPlayer src={videoUrl} autoPlay loop />
            <div style={{ marginTop: "12px", fontSize: "0.75rem", color: "var(--text-muted)" }}>
              {playingVideo.domain.toUpperCase()} • {new Date(playingVideo.created_at).toLocaleDateString()}
            </div>
          </div>
        </div>
      )}

      <style>{`
        .video-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 20px;
        }

        .video-modal {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.9);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 40px;
        }

        .video-modal-content {
          background: rgba(0, 24, 40, 0.95);
          border: 1px solid var(--accent-cyan);
          border-radius: 8px;
          padding: 24px;
          max-width: 900px;
          width: 100%;
        }

        .filter-select {
          background: var(--bg-input);
          border: 1px solid var(--border-strong);
          color: var(--text-primary);
          padding: 8px 12px;
          font-family: var(--font-mono);
          font-size: 0.75rem;
          cursor: pointer;
        }

        .filter-select:focus {
          outline: 1px solid var(--accent-cyan);
        }

        .video-card {
          background: rgba(0, 20, 40, 0.8);
          border: 1px solid rgba(0, 240, 255, 0.2);
          border-radius: 4px;
          overflow: hidden;
          cursor: pointer;
          transition: transform 0.15s, border-color 0.15s;
        }

        .video-card:hover {
          transform: translateY(-2px);
          border-color: var(--accent-cyan);
        }

        .video-thumbnail {
          position: relative;
          aspect-ratio: 16 / 9;
          background: #000;
          overflow: hidden;
        }

        .thumbnail-video {
          width: 100%;
          height: 100%;
          object-fit: cover;
          opacity: 0.8;
        }

        .thumbnail-placeholder {
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(0, 20, 40, 0.5);
        }

        .play-overlay {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(0, 0, 0, 0.4);
          opacity: 0;
          transition: opacity 0.15s;
        }

        .video-card:hover .play-overlay {
          opacity: 1;
        }

        .play-icon {
          font-size: 2rem;
          color: white;
          text-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
        }

        .duration-badge {
          position: absolute;
          bottom: 8px;
          right: 8px;
          background: rgba(0, 0, 0, 0.8);
          color: white;
          padding: 2px 6px;
          border-radius: 2px;
          font-size: 0.7rem;
          font-family: var(--font-mono);
        }

        .video-info {
          padding: 12px;
        }

        .video-meta-top {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }

        .domain-badge {
          font-size: 0.6rem;
          padding: 2px 6px;
          border: 1px solid;
          border-radius: 2px;
          letter-spacing: 0.1em;
        }

        .quality-badge {
          font-size: 0.75rem;
          font-weight: 600;
        }

        .video-prompt {
          font-size: 0.85rem;
          color: var(--text-secondary);
          line-height: 1.4;
          margin: 0 0 12px 0;
          min-height: 2.8em;
        }

        .video-meta-bottom {
          display: flex;
          justify-content: space-between;
          font-size: 0.7rem;
          color: var(--text-muted);
        }
      `}</style>
    </>
  );
}
