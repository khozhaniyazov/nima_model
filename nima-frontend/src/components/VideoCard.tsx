"use client";

import { useState } from "react";
import type { Video } from "@/lib/api";

interface VideoCardProps {
  video: Video;
  onPlay: (video: Video) => void;
}

export function VideoCard({ video, onPlay }: VideoCardProps) {
  const [imageError, setImageError] = useState(false);

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric"
    });
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getDomainColor = (domain: string) => {
    const colors: Record<string, string> = {
      math: "#00f0ff",
      physics: "#ff00ff",
      cs: "#00ff88",
      chemistry: "#ffff00",
    };
    return colors[domain.toLowerCase()] || "#888888";
  };

  const qualityScore = video.overall_score;
  const qualityColor = qualityScore && qualityScore >= 80 ? "#00ff66" 
    : qualityScore && qualityScore >= 60 ? "#fcee0a" 
    : "#ff003c";

  return (
    <div 
      className="video-card"
      onClick={() => onPlay(video)}
    >
      <div className="video-thumbnail">
        {imageError ? (
          <div className="thumbnail-placeholder">
            <span style={{ fontSize: "2rem", opacity: 0.5 }}>▶</span>
          </div>
        ) : (
          <video 
            src={video.organized_path}
            className="thumbnail-video"
            preload="metadata"
            onError={() => setImageError(true)}
          />
        )}
        <div className="play-overlay">
          <span className="play-icon">▶</span>
        </div>
        {video.duration_seconds && (
          <span className="duration-badge">
            {Math.floor(video.duration_seconds / 60)}:{String(Math.floor(video.duration_seconds % 60)).padStart(2, "0")}
          </span>
        )}
      </div>

      <div className="video-info">
        <div className="video-meta-top">
          <span 
            className="domain-badge"
            style={{ borderColor: getDomainColor(video.domain) }}
          >
            {video.domain.toUpperCase()}
          </span>
          {qualityScore && (
            <span 
              className="quality-badge"
              style={{ color: qualityColor }}
            >
              ★ {qualityScore.toFixed(0)}
            </span>
          )}
        </div>

        <p className="video-prompt" title={video.prompt}>
          {video.prompt.length > 80 ? `${video.prompt.substring(0, 80)}...` : video.prompt}
        </p>

        <div className="video-meta-bottom">
          <span className="video-date">{formatDate(video.created_at)}</span>
          <span className="video-size">{formatFileSize(video.file_size_bytes)}</span>
        </div>
      </div>
    </div>
  );
}

export default VideoCard;
