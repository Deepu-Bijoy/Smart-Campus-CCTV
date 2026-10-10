import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { 
  ArrowLeft, 
  Download, 
  FileText, 
  Video, 
  Clock, 
  Users, 
  X, 
  Maximize2,
  Loader2,
  Image as ImageIcon,
  Trash2,
  AlertTriangle
} from 'lucide-react';
import { AuthenticatedImage } from '../components/AuthenticatedImage';

interface VerifiedStudent {
  id: string;
  name: string;
  rollNumber: string;
  className?: string | null;
  department?: string | null;
  semesterYear?: string | null;
  section?: string | null;
  profilePhotoUrl?: string | null;
}

const formatSemesterYear = (semester?: number | string | null, year?: number | string | null): string => {
  const hasSem = semester !== undefined && semester !== null && semester !== '' && semester !== 0;
  const hasYr = year !== undefined && year !== null && year !== '' && year !== 0;
  if (hasSem && hasYr) {
    return `Semester ${semester} (Year ${year})`;
  }
  if (hasSem) return `Semester ${semester}`;
  if (hasYr) return `Year ${year}`;
  return 'Not available';
};

export const ReportDetails: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [isEnlarged, setIsEnlarged] = useState(false);
  const [downloadingFormat, setDownloadingFormat] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Fetch report details
  const { data: report, isLoading } = useQuery({
    queryKey: ['report-detail', id],
    queryFn: async () => {
      const response = await api.get(`/reports/${id}`);
      return response.data;
    }
  });

  const d = report?.data || {};
  const videoInfo = d.video_info || {};
  const evidenceInfo = d.evidence || {};
  const eventInfo = d.event_info || {};

  // Fetch video asset details to resolve original filename if video_id is present
  const videoId = videoInfo.video_id;
  const { data: videoData } = useQuery({
    queryKey: ['video-asset', videoId],
    queryFn: async () => {
      if (!videoId) return null;
      try {
        const res = await api.get(`/videos/${videoId}`);
        return res.data;
      } catch {
        return null;
      }
    },
    enabled: Boolean(videoId)
  });

  // Fetch incident evidences as fallback if not in report data
  const incidentId = report?.incident_id || d.incident_id;
  const { data: incidentEvidences } = useQuery({
    queryKey: ['incident-evidence', incidentId],
    queryFn: async () => {
      if (!incidentId) return [];
      try {
        const res = await api.get(`/evidence/${incidentId}`);
        return res.data || [];
      } catch {
        return [];
      }
    },
    enabled: Boolean(incidentId && !evidenceInfo.evidence_image && !evidenceInfo.image_url)
  });

  // Handle ESC key for image lightbox
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsEnlarged(false);
      }
    };
    if (isEnlarged) {
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isEnlarged]);

  // Download report in HTML or JSON format
  const handleDownload = async (format: string) => {
    if (downloadingFormat || !id) return;
    setDownloadingFormat(format);
    setDownloadError(null);

    try {
      const response = await api.get(`/reports/download/${id}`, {
        params: { format },
        responseType: 'blob'
      });

      let filename = `${(report?.title || 'report').toLowerCase().replace(/\s+/g, '_')}.${format === 'json' ? 'json' : 'html'}`;
      const disposition = response.headers['content-disposition'];
      if (disposition && disposition.includes('filename=')) {
        const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
        if (match && match[1]) {
          filename = match[1].replace(/['"]/g, '');
        }
      }

      const mimeType = format === 'json' ? 'application/json' : 'text/html';
      const blob = new Blob([response.data], { type: mimeType });
      const blobUrl = window.URL.createObjectURL(blob);

      const link = document.createElement('a');
      link.href = blobUrl;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      window.URL.revokeObjectURL(blobUrl);
    } catch (err: any) {
      console.error('Failed to download report:', err);
      let errMsg = 'Failed to download report file. Please verify permissions.';
      if (err.response?.status === 401) {
        errMsg = 'Session expired. Please log in again.';
      } else if (err.response?.status === 403) {
        errMsg = 'Permission denied.';
      } else if (err.response?.status === 404) {
        errMsg = 'Report download file not found.';
      }
      setDownloadError(errMsg);
    } finally {
      setDownloadingFormat(null);
    }
  };

  const handleDeleteReport = async () => {
    if (!id || isDeleting) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await api.delete(`/reports/${id}`);
      navigate('/reports');
    } catch (err: any) {
      console.error('Failed to delete report:', err);
      let errMsg = 'Failed to delete report. Please check your authorization.';
      if (err.response?.status === 403) {
        errMsg = 'Permission denied. Only administrators or the report creator can delete this report.';
      } else if (err.response?.data?.detail) {
        errMsg = err.response.data.detail;
      }
      setDeleteError(errMsg);
      setIsDeleting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 h-96">
        <div className="flex items-center space-x-2 animate-pulse text-sm">
          <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
          <span>Loading forensic report...</span>
        </div>
      </div>
    );
  }

  // --- 1. RESOLVE EVIDENCE SCREENSHOT ---
  const resolveScreenshotUrl = (): string | null => {
    if (evidenceInfo.evidence_image) return evidenceInfo.evidence_image;
    if (evidenceInfo.image_url) return evidenceInfo.image_url;
    if (Array.isArray(evidenceInfo.items)) {
      const item = evidenceInfo.items.find((it: any) => it.type === 'screenshot' || it.type === 'image');
      if (item?.url) return item.url;
    }
    if (Array.isArray(d.timeline)) {
      const item = d.timeline.find((it: any) => it.type === 'screenshot' || it.type === 'image');
      if (item?.url) return item.url;
    }
    if (incidentEvidences && Array.isArray(incidentEvidences)) {
      const ev = incidentEvidences.find((e: any) => e.evidence_type === 'screenshot' || e.evidence_type === 'image');
      if (ev?.file_path) {
        const path = ev.file_path.replace(/\\/g, '/');
        return path.startsWith('/') ? path : `/${path}`;
      }
    }
    return null;
  };
  const screenshotUrl = resolveScreenshotUrl();

  // --- 2. RESOLVE SOURCE VIDEO NAME (NO RAW UUIDs) ---
  const isUuid = (str?: string | null): boolean => {
    if (!str) return false;
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(\.[a-z0-9]+)?$/i.test(str.trim()) ||
           /^[0-9a-f]{32}(\.[a-z0-9]+)?$/i.test(str.trim());
  };

  const resolveVideoName = (): string => {
    // 1. From fetched video entity
    if (videoData?.original_filename && !isUuid(videoData.original_filename)) {
      return videoData.original_filename;
    }
    // 2. From report data video_info.original_filename
    if (videoInfo.original_filename && !isUuid(videoInfo.original_filename)) {
      return videoInfo.original_filename;
    }
    // 3. From video_info.title if not a UUID
    if (videoInfo.title && !isUuid(videoInfo.title)) {
      const title = videoInfo.title.trim();
      return title.toLowerCase().endsWith('.mp4') ? title : `${title}.mp4`;
    }
    // 4. From report title (e.g., "Violence Incident Report - WhatsApp Video 2026-07-27 at 10.29.42 PM.mp4")
    if (report?.title) {
      const cleaned = report.title.replace(/^.*Report\s*-\s*/i, '').trim();
      if (cleaned && !isUuid(cleaned) && cleaned.includes('.')) {
        return cleaned;
      }
    }
    // 5. From video_info.filename if not a UUID
    if (videoInfo.filename && !isUuid(videoInfo.filename)) {
      return videoInfo.filename;
    }
    // 6. From fetched videoData.title
    if (videoData?.title && !isUuid(videoData.title)) {
      const title = videoData.title.trim();
      return title.toLowerCase().endsWith('.mp4') ? title : `${title}.mp4`;
    }
    return 'CCTV_Footage.mp4';
  };
  const videoName = resolveVideoName();

  // --- 3. RESOLVE SCREENSHOT TIMESTAMP (FORMAT 00:00:12) ---
  const formatSeconds = (sec: number): string => {
    if (isNaN(sec) || sec < 0) return '00:00:00';
    const totalSecs = Math.floor(sec);
    const hrs = Math.floor(totalSecs / 3600);
    const mins = Math.floor((totalSecs % 3600) / 60);
    const secs = totalSecs % 60;
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  const resolveScreenshotTimestamp = (): string => {
    // Check explanation or narrative text for explicit seconds offset in video
    const text = `${d.explanation || ''} ${d.narrative_summary || ''}`;
    const rangeMatch = text.match(/altercation from\s*([0-9]+(?:\.[0-9]+)?)\s*s/i);
    if (rangeMatch) {
      return formatSeconds(parseFloat(rangeMatch[1]));
    }
    const singleMatch = text.match(/(?:at|from)\s*([0-9]+(?:\.[0-9]+)?)\s*s/i);
    if (singleMatch) {
      return formatSeconds(parseFloat(singleMatch[1]));
    }

    // Check numerical timestamp fields
    if (typeof d.timestamp_seconds === 'number') {
      return formatSeconds(d.timestamp_seconds);
    }
    if (typeof evidenceInfo.timestamp_seconds === 'number') {
      return formatSeconds(evidenceInfo.timestamp_seconds);
    }
    if (typeof eventInfo.timestamp_seconds === 'number') {
      return formatSeconds(eventInfo.timestamp_seconds);
    }
    if (typeof eventInfo.start_time === 'number') {
      return formatSeconds(eventInfo.start_time);
    }

    // Check evidence image URL segment naming pattern
    const imgUrl = `${screenshotUrl || ''}`;
    const segMatch = imgUrl.match(/_seg([0-9]+)\./i);
    if (segMatch) {
      const segNum = parseInt(segMatch[1], 10);
      return segNum === 0 ? '00:00:01' : '00:00:06';
    }

    // Check timeline formatted items
    if (Array.isArray(d.timeline)) {
      for (const item of d.timeline) {
        if (item.time && /^([0-9]{2}:[0-9]{2}:[0-9]{2})$/.test(item.time)) {
          return item.time;
        }
      }
    }

    return '00:00:00';
  };
  const screenshotTimestamp = resolveScreenshotTimestamp();

  // --- 4. RESOLVE IDENTIFIED STUDENTS (DEDUPLICATED & VERIFIED ONLY) ---
  const resolveVerifiedStudents = (): VerifiedStudent[] => {
    const map = new Map<string, VerifiedStudent>();

    // 1. From involved_students
    if (Array.isArray(d.involved_students)) {
      for (const s of d.involved_students) {
        const isVerified = s.is_identified !== false && s.confidence !== 'unidentified';
        if (s.name && s.name !== 'Unidentified Person' && !s.name.toLowerCase().includes('unknown') && isVerified) {
          const key = (s.student_id || s.roll_number || s.name).toLowerCase();
          if (!map.has(key)) {
            const semYr = formatSemesterYear(s.semester, s.year);
            map.set(key, {
              id: s.student_id || key,
              name: s.name,
              rollNumber: s.roll_number || s.university_roll_number || 'Not available',
              className: s.class_name || s.class || s.programme || 'Not available',
              department: s.department || 'Not available',
              semesterYear: semYr,
              section: s.section || 'Not available',
              profilePhotoUrl: s.profile_photo_url || s.photo_url || null
            });
          }
        }
      }
    }

    // 2. From student_info (single subject reports)
    if (d.student_info && d.student_info.name && d.student_info.name !== 'Unidentified Person' && !d.student_info.name.toLowerCase().includes('unknown')) {
      const s = d.student_info;
      const isVerified = s.confidence === 'high' || s.confidence === 'medium';
      if (isVerified) {
        const key = (s.student_id || s.roll_number || s.name).toLowerCase();
        if (!map.has(key)) {
          const semYr = formatSemesterYear(s.semester, s.year);
          map.set(key, {
            id: s.student_id || key,
            name: s.name,
            rollNumber: s.roll_number || s.university_roll_number || 'Not available',
            className: s.class_name || s.class || s.programme || 'Not available',
            department: s.department || 'Not available',
            semesterYear: semYr,
            section: s.section || 'Not available',
            profilePhotoUrl: s.profile_photo_url || s.photo_url || null
          });
        }
      }
    }

    return Array.from(map.values());
  };
  const verifiedStudents = resolveVerifiedStudents();

  return (
    <div className="max-w-5xl mx-auto py-6 px-4 space-y-6">
      {/* Top Navigation Bar */}
      <div className="flex items-center justify-between border-b border-slate-200 pb-4">
        <button
          onClick={() => navigate('/reports')}
          className="inline-flex items-center space-x-2 text-slate-600 hover:text-slate-900 transition text-sm font-semibold cursor-pointer"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Reports</span>
        </button>

        <div className="flex items-center space-x-2.5">
          <button
            onClick={() => handleDownload('html')}
            disabled={Boolean(downloadingFormat)}
            className="inline-flex items-center space-x-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition border border-slate-300 disabled:opacity-50 cursor-pointer"
            title="Download report file"
          >
            {downloadingFormat === 'html' ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            <span>Download</span>
          </button>
          <button
            onClick={() => handleDownload('json')}
            disabled={Boolean(downloadingFormat)}
            className="inline-flex items-center space-x-1.5 bg-white hover:bg-slate-50 text-slate-700 px-3 py-1.5 rounded-lg text-xs font-semibold transition border border-slate-300 disabled:opacity-50 cursor-pointer"
            title="Export report JSON data"
          >
            {downloadingFormat === 'json' ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <FileText className="h-3.5 w-3.5" />
            )}
            <span>JSON</span>
          </button>
          <button
            onClick={() => {
              setDeleteError(null);
              setShowDeleteModal(true);
            }}
            disabled={isDeleting}
            className="inline-flex items-center space-x-1.5 bg-red-50 hover:bg-red-100 text-red-600 px-3 py-1.5 rounded-lg text-xs font-semibold transition border border-red-200 disabled:opacity-50 cursor-pointer"
            title="Delete this forensic report"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>Delete Report</span>
          </button>
        </div>
      </div>

      {downloadError && (
        <div className="text-xs text-red-700 bg-red-50 border border-red-200 px-3 py-2 rounded-lg">
          {downloadError}
        </div>
      )}

      {/* Main Forensic Report Card */}
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-slate-200">
          
          {/* A. EVIDENCE SCREENSHOT (HERO SECTION) */}
          <div className="lg:col-span-7 p-6 flex flex-col justify-center">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <span className="flex items-center space-x-1.5">
                  <ImageIcon className="h-3.5 w-3.5 text-slate-400" />
                  <span>Evidence Screenshot</span>
                </span>
                {screenshotUrl && (
                  <span className="text-[11px] text-blue-600 font-normal lowercase">Click to enlarge</span>
                )}
              </div>

              {screenshotUrl ? (
                <div 
                  onClick={() => setIsEnlarged(true)}
                  className="group relative rounded-xl overflow-hidden bg-slate-950 border border-slate-200 aspect-video flex items-center justify-center cursor-pointer shadow-inner hover:ring-2 hover:ring-blue-500/50 transition"
                >
                  <AuthenticatedImage
                    src={screenshotUrl}
                    alt="Forensic Evidence Keyframe"
                    className="w-full h-full object-contain transition group-hover:scale-[1.01]"
                  />
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition flex items-center justify-center opacity-0 group-hover:opacity-100">
                    <span className="inline-flex items-center space-x-1.5 bg-black/75 text-white text-xs px-3 py-1.5 rounded-lg backdrop-blur-sm shadow-md">
                      <Maximize2 className="h-3.5 w-3.5" />
                      <span>Enlarge Image</span>
                    </span>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 aspect-video flex flex-col items-center justify-center text-slate-400 space-y-2">
                  <ImageIcon className="h-8 w-8 text-slate-300" />
                  <span className="text-xs">No evidence screenshot captured</span>
                </div>
              )}
            </div>
          </div>

          {/* B, C, D. VIDEO NAME, TIMESTAMP & STUDENT DETAILS */}
          <div className="lg:col-span-5 p-6 flex flex-col justify-between space-y-6 bg-slate-50/50">
            
            {/* Top Details: Video Name & Timestamp */}
            <div className="space-y-5">
              {/* B. Source Video Name */}
              <div className="space-y-1.5">
                <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  <Video className="h-3.5 w-3.5 text-slate-400" />
                  <span>Source Video</span>
                </div>
                <div className="p-3 bg-white border border-slate-200 rounded-xl">
                  <span className="text-sm font-mono font-semibold text-slate-800 break-all select-all block">
                    {videoName}
                  </span>
                </div>
              </div>

              {/* C. Screenshot Timestamp */}
              <div className="space-y-1.5">
                <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  <Clock className="h-3.5 w-3.5 text-slate-400" />
                  <span>Screenshot Timestamp</span>
                </div>
                <div className="p-3 bg-white border border-slate-200 rounded-xl flex items-baseline space-x-2">
                  <span className="text-lg font-mono font-bold text-slate-900 tracking-wider">
                    {screenshotTimestamp}
                  </span>
                  <span className="text-xs text-slate-400 font-sans">(source video time)</span>
                </div>
              </div>
            </div>

            {/* D. Identified Student Details */}
            <div className="space-y-2 pt-2 border-t border-slate-200">
              <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <Users className="h-3.5 w-3.5 text-slate-400" />
                <span>Identified Students</span>
              </div>

              {verifiedStudents.length > 0 ? (
                <div className="space-y-3">
                  {verifiedStudents.map((st) => (
                    <div 
                      key={st.id} 
                      className="p-3.5 bg-white border border-slate-200 rounded-xl shadow-xs space-y-2.5 transition hover:border-slate-300"
                    >
                      <div className="flex items-center space-x-3 pb-2.5 border-b border-slate-100">
                        {st.profilePhotoUrl ? (
                          <AuthenticatedImage
                            src={st.profilePhotoUrl}
                            alt={st.name}
                            className="w-11 h-11 rounded-full object-cover border border-slate-200 bg-slate-100 shrink-0 shadow-xs"
                          />
                        ) : (
                          <div className="w-11 h-11 rounded-full bg-blue-50 border border-blue-200 text-blue-700 flex items-center justify-center font-bold text-base shrink-0 shadow-xs">
                            {st.name.charAt(0).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <span className="text-sm font-bold text-slate-900 block truncate leading-tight">
                            {st.name}
                          </span>
                          <span className="text-xs font-mono text-slate-500 block truncate mt-0.5">
                            Roll No.: <span className="font-semibold text-slate-800">{st.rollNumber}</span>
                          </span>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block text-[11px] font-medium">Class</span>
                          <span className="font-semibold text-slate-800 block truncate">
                            {st.className || 'Not available'}
                          </span>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block text-[11px] font-medium">Department</span>
                          <span className="font-semibold text-slate-800 block truncate">
                            {st.department || 'Not available'}
                          </span>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block text-[11px] font-medium">Semester / Year</span>
                          <span className="font-semibold text-slate-800 block truncate">
                            {st.semesterYear || 'Not available'}
                          </span>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block text-[11px] font-medium">Section</span>
                          <span className="font-semibold text-slate-800 block truncate">
                            {st.section || 'Not available'}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-4 bg-white border border-dashed border-slate-300 rounded-xl text-center">
                  <span className="text-xs text-slate-500 italic block">
                    No confirmed student identities
                  </span>
                </div>
              )}
            </div>

          </div>
        </div>
      </div>

      {/* Lightbox Enlargement Modal */}
      {isEnlarged && screenshotUrl && (
        <div 
          onClick={() => setIsEnlarged(false)}
          className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4 sm:p-8"
        >
          <div 
            onClick={(e) => e.stopPropagation()} 
            className="bg-slate-900 border border-slate-700 rounded-2xl max-w-5xl w-full p-4 space-y-3 relative shadow-2xl overflow-hidden"
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2 text-slate-300 text-xs font-mono truncate">
                <span className="font-semibold text-white">{videoName}</span>
                <span className="text-slate-500">•</span>
                <span>{screenshotTimestamp}</span>
              </div>
              <button
                type="button"
                onClick={() => setIsEnlarged(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition cursor-pointer"
                title="Close enlargement"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Modal Image */}
            <div className="rounded-xl overflow-hidden bg-black max-h-[80vh] flex items-center justify-center">
              <AuthenticatedImage
                src={screenshotUrl}
                alt="Enlarged Forensic Evidence Keyframe"
                className="w-full h-full object-contain max-h-[80vh]"
              />
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-slate-200 space-y-4">
            <div className="flex items-center space-x-3 text-red-600">
              <div className="p-2.5 bg-red-50 rounded-xl border border-red-100">
                <AlertTriangle className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900">Delete Forensic Report</h3>
                <p className="text-xs text-slate-500">Confirm permanent report removal</p>
              </div>
            </div>
            <p className="text-sm text-slate-600 leading-relaxed">
              Are you sure you want to delete this forensic report? The report document record will be permanently deleted. The original CCTV video footage, evidence keyframes, and student profiles will remain preserved.
            </p>
            {deleteError && (
              <div className="text-xs text-red-700 bg-red-50 border border-red-200 p-2.5 rounded-lg">
                {deleteError}
              </div>
            )}
            <div className="flex justify-end space-x-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowDeleteModal(false);
                  setDeleteError(null);
                }}
                disabled={isDeleting}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-lg transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteReport}
                disabled={isDeleting}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-lg transition flex items-center space-x-1.5 disabled:opacity-50 cursor-pointer"
              >
                {isDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                <span>{isDeleting ? 'Deleting...' : 'Confirm Delete'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ReportDetails;
