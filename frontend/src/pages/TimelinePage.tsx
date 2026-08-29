import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { VideoPlayer } from '../components/VideoPlayer';
import { Timeline } from '../components/Timeline';
import type { TimelineItemData } from '../components/Timeline';
import { Film, User, Tag, Clock } from 'lucide-react';

export const TimelinePage: React.FC = () => {
  const { id } = useParams<{ id: string }>(); 
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(null);

  const { data: video, isLoading: isVideoLoading } = useQuery({
    queryKey: ['video-detail', id],
    queryFn: async () => {
      const res = await api.get(`/videos`);
      const list = res.data.items || [];
      return list.find((v: any) => v.id === id);
    }
  });

  const { data: tracks, isLoading: isTracksLoading } = useQuery({
    queryKey: ['video-tracks', id],
    queryFn: async () => {
      const res = await api.get(`/videos/${id}/tracks`);
      return res.data || [];
    }
  });

  const { data: identifiedStudent } = useQuery({
    queryKey: ['track-student', selectedTrackId],
    queryFn: async () => {
      if (!selectedTrackId) return null;
      const res = await api.get(`/tracks/${selectedTrackId}/identified-student`);
      return res.data;
    },
    enabled: !!selectedTrackId
  });

  const { data: timelineItems } = useQuery({
    queryKey: ['track-timeline', selectedTrackId],
    queryFn: async () => {
      if (!selectedTrackId) return [];
      const res = await api.get(`/timeline/${selectedTrackId}`);
      return res.data || [];
    },
    enabled: !!selectedTrackId
  });

  if (isVideoLoading || isTracksLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <p className="animate-pulse">Loading video tracking files...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 py-2">
      <div>
        <h2 className="text-2xl font-bold text-slate-100">Tracking Analysis</h2>
        <p className="text-slate-400 text-sm">Verify trajectory points, bounding box indices, and facial recognitions</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Column: Player and Timeline */}
        <div className="lg:col-span-2 space-y-6">
          {video && (
            <VideoPlayer src={video.file_path} poster="" autoplay={true} />
          )}

          {selectedTrackId ? (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md">
              <div className="flex items-center justify-between border-b border-dark-border/50 pb-4 mb-6">
                <div>
                  <h3 className="font-bold text-slate-200 text-lg">Target Trajectory Timeline</h3>
                  <p className="text-xs text-slate-400">Chronological points of interest for track {selectedTrackId.slice(0, 8)}</p>
                </div>
                {identifiedStudent?.student_id && (
                  <Link
                    to={`/students/${identifiedStudent.student_id}`}
                    className="flex items-center space-x-1.5 text-xs text-blue-400 bg-blue-500/10 border border-blue-500/20 px-3 py-1.5 rounded-lg hover:bg-blue-500/20 transition font-semibold"
                  >
                    <User className="h-4.5 w-4.5" />
                    <span>View Profile ({identifiedStudent.student_name})</span>
                  </Link>
                )}
              </div>
              <Timeline items={timelineItems as TimelineItemData[]} />
            </div>
          ) : (
            <div className="text-center py-20 text-slate-500 text-sm bg-dark-card border border-dark-border rounded-2xl">
              Select a trajectory track from the right side panel to map its spatial-temporal sequence.
            </div>
          )}
        </div>

        {/* Right Column: Track List */}
        <div className="space-y-6">
          <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
            <div className="flex items-center space-x-2 text-slate-300 font-semibold border-b border-dark-border pb-3 mb-4">
              <Film className="h-4 w-4 text-blue-500" />
              <span>Detections & Tracks</span>
            </div>

            <div className="space-y-3 max-h-[400px] overflow-y-auto pr-1">
              {tracks && tracks.length > 0 ? (
                tracks.map((tr: any) => (
                  <button
                    key={tr.id}
                    onClick={() => setSelectedTrackId(tr.id)}
                    className={`w-full text-left p-4 rounded-xl border transition flex flex-col justify-between space-y-2 ${
                      selectedTrackId === tr.id
                        ? 'bg-blue-600/10 border-blue-500 text-white'
                        : 'bg-slate-900/50 border-dark-border text-slate-300 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between w-full">
                      <span className="text-xs font-mono font-bold uppercase">Track #{tr.tracker_id}</span>
                      <span className="flex items-center text-[10px] text-slate-400 space-x-1">
                        <Clock className="h-3 w-3" />
                        <span>{tr.start_time.toFixed(1)}s - {tr.end_time.toFixed(1)}s</span>
                      </span>
                    </div>
                    <div className="flex items-center justify-between w-full text-xs">
                      <span className="flex items-center space-x-1 text-slate-400 capitalize">
                        <Tag className="h-3 w-3 text-slate-500" />
                        <span>{tr.object_class}</span>
                      </span>
                    </div>
                  </button>
                ))
              ) : (
                <div className="text-center py-8 text-slate-500 text-sm">
                  No tracks detected in this feed.
                </div>
              )}
            </div>
          </div>

          {/* Identified Student card */}
          {selectedTrackId && identifiedStudent && (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-md space-y-4">
              <div className="flex items-center space-x-2 text-slate-300 font-semibold border-b border-dark-border pb-3">
                <User className="h-4 w-4 text-blue-500" />
                <span>Facial Match Result</span>
              </div>
              {identifiedStudent.student_id ? (
                <div className="space-y-4">
                  <div>
                    <h4 className="font-semibold text-slate-200 text-sm">{identifiedStudent.student_name}</h4>
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border inline-block mt-2 ${
                      identifiedStudent.confidence === 'high'
                        ? 'bg-green-500/10 text-green-500 border-green-500/20'
                        : 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20'
                    }`}>
                      {(identifiedStudent.similarity_score * 100).toFixed(0)}% Match ({identifiedStudent.confidence})
                    </span>
                  </div>
                </div>
              ) : (
                <div className="text-slate-500 text-xs">
                  No verified student identity matching this track.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
