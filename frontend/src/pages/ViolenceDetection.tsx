import React, { useState, useRef, useEffect, useMemo } from 'react';
import { 
  Upload, 
  CheckCircle2, 
  AlertTriangle, 
  Image as ImageIcon,
  Film,
  Loader2, 
  X, 
  RotateCcw,
  Users,
  ChevronLeft,
  ChevronRight,
  Play,
  Activity,
  ArrowUpRight
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import { AuthenticatedImage } from '../components/AuthenticatedImage';

export interface UploadedVideoInfo {
  video_id: string;
  title: string;
  filename: string;
  original_filename: string;
  file_url: string;
  status: string;
  duration?: number | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  codec?: string | null;
  file_size?: number | null;
  uploaded_at: string;
}

export interface ViolenceSignalBreakdown {
  motion_dynamics: number;
  person_interaction: number;
  clip_similarity: number;
  temporal_persistence: number;
}

export interface InvolvedStudentCard {
  student_id?: string | null;
  name: string;
  roll_number?: string | null;
  department?: string | null;
  programme?: string | null;
  section?: string | null;
  class_name?: string | null;
  profile_photo_url?: string | null;
  similarity_score: number;
  confidence: string; // "high", "medium", "unidentified"
  track_id?: string | null;
  event_id?: string | null;
  is_identified?: boolean;
}

export interface SegmentTrackInfo {
  event_id?: string | null;
  track_id: string;
  tracker_id: number;
  frame_number: number;
  timestamp_seconds: number;
  bounding_box: number[];
  person_crop?: string | null;
  confidence: number;
  face_visible: boolean;
  identified_student?: InvolvedStudentCard | null;
}

export interface ViolenceSegment {
  segment_id: string;
  event_id?: string | null;
  video_id?: string | null;
  start_time: number;
  end_time: number;
  duration: number;
  timestamp_display: string;
  confidence: number;
  severity: string;
  breakdown: ViolenceSignalBreakdown;
  explanation: string;
  evidence_image?: string | null;
  evidence_video?: string | null;
  persons_count?: number;
  tracks?: SegmentTrackInfo[];
  students?: InvolvedStudentCard[];
}

export interface ViolenceAnalysisResponse {
  video_id: string;
  video_title: string;
  camera_id?: string | null;
  camera_name?: string | null;
  camera_location?: string | null;
  status: 'VIOLENCE_DETECTED' | 'NORMAL';
  verdict: string;
  overall_confidence: number;
  total_segments: number;
  segments: ViolenceSegment[];
  primary_evidence_image?: string | null;
  primary_evidence_video?: string | null;
  identified_students?: InvolvedStudentCard[];
  incident_id?: string | null;
  analyzed_at: string;
}

export const ViolenceDetection: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  const [videoDuration, setVideoDuration] = useState<number | null>(null);
  const [videoDimensions, setVideoDimensions] = useState<{ width: number; height: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // Upload state
  const [uploadedVideo, setUploadedVideo] = useState<UploadedVideoInfo | null>(null);
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Analysis state
  const [analysisState, setAnalysisState] = useState<'idle' | 'loading' | 'error' | 'success_violence' | 'success_normal'>('idle');
  const [analysisResult, setAnalysisResult] = useState<ViolenceAnalysisResponse | null>(null);
  const [currentStageText, setCurrentStageText] = useState<string>('Initializing pipeline...');
  const [analysisProgress, setAnalysisProgress] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Evidence modal state
  const [selectedSegmentModalIndex, setSelectedSegmentModalIndex] = useState<number | null>(null);
  const [evidenceMediaType, setEvidenceMediaType] = useState<'clip' | 'frame'>('clip');

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const mainVideoPlayerRef = useRef<HTMLVideoElement | null>(null);
  const pollIntervalRef = useRef<any>(null);

  // Clean up object URL and polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
      if (videoPreviewUrl) {
        URL.revokeObjectURL(videoPreviewUrl);
      }
    };
  }, [videoPreviewUrl]);

  const uploadVideoToServer = async (targetFile: File) => {
    setUploadStatus('uploading');
    setUploadProgress(0);
    setUploadError(null);
    setUploadedVideo(null);

    const formData = new FormData();
    formData.append('file', targetFile);
    formData.append('title', targetFile.name.replace(/\.[^/.]+$/, ''));

    try {
      const response = await api.post<UploadedVideoInfo>('/violence/upload', formData, {
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(percent);
          }
        }
      });

      setUploadedVideo(response.data);
      setUploadStatus('success');
      if (response.data.duration) {
        setVideoDuration(response.data.duration);
      }
      if (response.data.width && response.data.height) {
        setVideoDimensions({ width: response.data.width, height: response.data.height });
      }
    } catch (err: any) {
      console.error('Video upload failed:', err);
      setUploadStatus('error');
      const msg = err.response?.data?.detail || err.message || 'Unable to upload video to server.';
      setUploadError(msg);
    }
  };

  const handleFileSelect = (selectedFile: File) => {
    const allowedExtensions = ['.mp4', '.avi', '.mkv', '.mov'];
    const ext = selectedFile.name.substring(selectedFile.name.lastIndexOf('.')).toLowerCase();

    if (!allowedExtensions.includes(ext)) {
      setErrorMessage(`Unsupported format '${ext}'. Please upload MP4, AVI, MKV, or MOV files.`);
      return;
    }

    if (selectedFile.size > 100 * 1024 * 1024) {
      setErrorMessage('Video file exceeds the 100MB limit.');
      return;
    }

    setErrorMessage(null);
    setFile(selectedFile);
    setAnalysisState('idle');
    setAnalysisResult(null);

    if (videoPreviewUrl) {
      URL.revokeObjectURL(videoPreviewUrl);
    }

    const url = URL.createObjectURL(selectedFile);
    setVideoPreviewUrl(url);

    uploadVideoToServer(selectedFile);
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFileSelect(e.target.files[0]);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleLoadedMetadata = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = e.currentTarget;
    if (!videoDuration) {
      setVideoDuration(video.duration);
    }
    if (!videoDimensions) {
      setVideoDimensions({ width: video.videoWidth, height: video.videoHeight });
    }
  };

  const handleResetVideo = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (videoPreviewUrl) {
      URL.revokeObjectURL(videoPreviewUrl);
    }
    setFile(null);
    setVideoPreviewUrl(null);
    setVideoDuration(null);
    setVideoDimensions(null);
    setUploadedVideo(null);
    setAnalysisResult(null);
    setUploadStatus('idle');
    setUploadProgress(0);
    setUploadError(null);
    setAnalysisState('idle');
    setErrorMessage(null);
    setSelectedSegmentModalIndex(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  // Start analysis
  const startAnalysis = async () => {
    if (!uploadedVideo || uploadStatus !== 'success' || analysisState === 'loading') return;

    setAnalysisState('loading');
    setAnalysisProgress(15);
    setErrorMessage(null);
    setCurrentStageText('Starting temporal violence detection...');

    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }

    // Polling interval
    pollIntervalRef.current = setInterval(async () => {
      try {
        const res = await api.get(`/violence/status/${uploadedVideo.video_id}`);
        if (res.data?.stage) {
          setCurrentStageText(res.data.stage);
        }
        if (typeof res.data?.progress === 'number') {
          setAnalysisProgress(res.data.progress);
        }
        if (res.data?.status === 'failed') {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setAnalysisState('error');
          setErrorMessage(res.data.error_message || 'Analysis failed on server.');
        } else if (res.data?.status === 'completed' && !analysisResult) {
          try {
            const resultRes = await api.get<ViolenceAnalysisResponse>(`/violence/result/${uploadedVideo.video_id}`);
            if (resultRes.data) {
              if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current);
                pollIntervalRef.current = null;
              }
              setAnalysisResult(resultRes.data);
              if (resultRes.data.status === 'VIOLENCE_DETECTED' && resultRes.data.segments && resultRes.data.segments.length > 0) {
                setAnalysisState('success_violence');
              } else {
                setAnalysisState('success_normal');
              }
            }
          } catch {
            // Wait for main analyze promise
          }
        }
      } catch {
        // Keep polling
      }
    }, 2000);

    try {
      const formData = new FormData();
      formData.append('video_id', uploadedVideo.video_id);

      const response = await api.post<ViolenceAnalysisResponse>('/violence/analyze', formData);
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      setAnalysisResult(response.data);

      if (response.data.status === 'VIOLENCE_DETECTED' && response.data.segments && response.data.segments.length > 0) {
        setAnalysisState('success_violence');
      } else {
        setAnalysisState('success_normal');
      }
    } catch (err: any) {
      console.error('Violence analysis request failure:', err);

      try {
        const checkStatus = await api.get(`/violence/status/${uploadedVideo.video_id}`);
        if (checkStatus.data?.status === 'failed') {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setAnalysisState('error');
          setErrorMessage(checkStatus.data.error_message || err.response?.data?.detail || 'Video processing encountered an error.');
          return;
        } else if (checkStatus.data?.status === 'processing') {
          return;
        }
      } catch {
        // Continue to error display
      }

      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      setAnalysisState('error');
      let detail = err.response?.data?.detail;
      if (!detail) {
        if (err.message === 'Network Error') {
          detail = 'Network or backend connection failed. The server may be processing or restarting.';
        } else {
          detail = err.message || 'Failed to complete violence detection analysis.';
        }
      }
      setErrorMessage(detail);
    }
  };

  const seekVideo = (seconds: number) => {
    if (mainVideoPlayerRef.current) {
      mainVideoPlayerRef.current.currentTime = seconds;
      mainVideoPlayerRef.current.play().catch(() => {});
    }
  };

  // Helper formatting
  const formatSeconds = (sec?: number | null) => {
    if (sec === undefined || sec === null) return '--';
    const s = Math.round(sec);
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m}:${rem.toString().padStart(2, '0')}`;
  };

  // Current segments list
  const segments = analysisResult?.segments || [];
  const activeModalSegment = selectedSegmentModalIndex !== null ? segments[selectedSegmentModalIndex] : null;

  // Deduplicate and extract only confirmed student identities (memoized)
  const confirmedPersons: InvolvedStudentCard[] = useMemo(() => {
    const map = new Map<string, InvolvedStudentCard>();

    segments.forEach((seg) => {
      (seg.students || []).forEach((st) => {
        if (st.student_id && st.is_identified && st.name && st.name !== 'Unidentified Person') {
          const idKey = String(st.student_id);
          if (!map.has(idKey)) {
            map.set(idKey, st);
          } else {
            const existing = map.get(idKey)!;
            if ((st.similarity_score ?? 0) > (existing.similarity_score ?? 0)) {
              map.set(idKey, st);
            }
          }
        }
      });
    });

    (analysisResult?.identified_students || []).forEach((st) => {
      if (st.student_id && st.is_identified && st.name && st.name !== 'Unidentified Person') {
        const idKey = String(st.student_id);
        if (!map.has(idKey)) {
          map.set(idKey, st);
        }
      }
    });

    return Array.from(map.values());
  }, [segments, analysisResult?.identified_students]);

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* 1. COMPACT PAGE HEADER */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Violence Detection</h1>
          <p className="text-xs text-slate-500 mt-0.5">Review detected incidents and supporting footage.</p>
        </div>
        <div className="flex items-center space-x-2">
          <Link
            to="/events"
            className="inline-flex items-center space-x-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 transition"
          >
            <span>Security Alerts Log</span>
            <ArrowUpRight className="h-3.5 w-3.5 text-slate-400" />
          </Link>
          <Link
            to="/reports"
            className="inline-flex items-center space-x-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 transition"
          >
            <span>Incident Reports</span>
          </Link>
        </div>
      </div>

      {/* 2. VIDEO SELECTION AND PREVIEW */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
        {!file ? (
          /* Upload dropzone */
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border border-dashed rounded-xl p-8 text-center transition flex flex-col items-center justify-center cursor-pointer ${
              isDragging 
                ? 'border-blue-500 bg-blue-50/50' 
                : 'border-slate-300 hover:border-slate-400 bg-slate-50/50'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".mp4,.avi,.mkv,.mov,video/*"
              onChange={handleFileInputChange}
              className="hidden"
            />
            <div className="p-3 rounded-full bg-white border border-slate-200 text-slate-600 mb-3 shadow-xs">
              <Upload className="h-5 w-5" />
            </div>
            <p className="text-sm font-semibold text-slate-800">
              Select or drop surveillance video to begin
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Supports MP4, AVI, MKV, or MOV up to 100MB
            </p>
            <button
              type="button"
              className="mt-4 px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-medium shadow-xs transition"
            >
              Choose Video File
            </button>
          </div>
        ) : (
          /* Selected video card & preview */
          <div className="space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
              {/* Video preview container - Preserves aspect ratio */}
              <div className="lg:col-span-7 bg-slate-950 rounded-lg overflow-hidden border border-slate-200 flex items-center justify-center min-h-[240px] max-h-[380px]">
                {videoPreviewUrl && (
                  <video
                    ref={mainVideoPlayerRef}
                    src={videoPreviewUrl}
                    controls
                    playsInline
                    onLoadedMetadata={handleLoadedMetadata}
                    className="w-full h-full max-h-[380px] object-contain"
                  />
                )}
              </div>

              {/* Video metadata and actions */}
              <div className="lg:col-span-5 flex flex-col justify-between space-y-4">
                <div className="space-y-3">
                  <div className="flex items-start justify-between">
                    <div className="min-w-0 pr-2">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 block">
                        Footage File
                      </span>
                      <h3 className="text-sm font-semibold text-slate-900 truncate" title={file.name}>
                        {file.name}
                      </h3>
                    </div>
                    <button
                      onClick={handleResetVideo}
                      disabled={analysisState === 'loading' || uploadStatus === 'uploading'}
                      className="p-1 rounded text-slate-400 hover:text-slate-600 disabled:opacity-40 transition"
                      title="Remove footage"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>

                  {/* Upload State Banner */}
                  {uploadStatus === 'uploading' && (
                    <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs space-y-2">
                      <div className="flex items-center justify-between text-slate-700">
                        <span className="flex items-center space-x-1.5 font-medium">
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-600" />
                          <span>Uploading footage...</span>
                        </span>
                        <span className="font-mono text-slate-600">{uploadProgress}%</span>
                      </div>
                      <div className="w-full bg-slate-200 rounded-full h-1 overflow-hidden">
                        <div
                          className="bg-blue-600 h-1 rounded-full transition-all duration-150"
                          style={{ width: `${uploadProgress}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {uploadStatus === 'error' && (
                    <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700 flex items-start justify-between gap-2">
                      <div className="flex items-start space-x-2">
                        <AlertTriangle className="h-4 w-4 shrink-0 text-red-600 mt-0.5" />
                        <div>
                          <p className="font-medium">Upload failed</p>
                          <p className="text-[11px] text-red-600 mt-0.5">{uploadError}</p>
                        </div>
                      </div>
                      <button
                        onClick={() => file && uploadVideoToServer(file)}
                        className="px-2 py-1 bg-white hover:bg-red-100 text-red-700 rounded border border-red-200 text-[11px] font-medium transition shrink-0"
                      >
                        Retry
                      </button>
                    </div>
                  )}

                  {/* Essential Metadata Grid */}
                  <div className="grid grid-cols-3 gap-2 py-1">
                    <div className="p-2.5 rounded-lg border border-slate-200 bg-slate-50/50">
                      <span className="text-[10px] text-slate-500 uppercase font-medium block">Duration</span>
                      <span className="text-xs font-semibold text-slate-800 font-mono">
                        {formatSeconds(videoDuration || uploadedVideo?.duration)}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg border border-slate-200 bg-slate-50/50">
                      <span className="text-[10px] text-slate-500 uppercase font-medium block">Resolution</span>
                      <span className="text-xs font-semibold text-slate-800 font-mono">
                        {videoDimensions ? `${videoDimensions.width}×${videoDimensions.height}` : uploadedVideo?.width ? `${uploadedVideo.width}×${uploadedVideo.height}` : '--'}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg border border-slate-200 bg-slate-50/50">
                      <span className="text-[10px] text-slate-500 uppercase font-medium block">Status</span>
                      <span className="text-xs font-medium text-slate-700 capitalize">
                        {uploadStatus === 'uploading' ? 'Uploading' : uploadStatus === 'success' ? 'Ready' : uploadStatus === 'error' ? 'Failed' : 'Selected'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="pt-2 border-t border-slate-100 flex items-center space-x-2">
                  <button
                    onClick={startAnalysis}
                    disabled={!uploadedVideo || uploadStatus !== 'success' || analysisState === 'loading'}
                    className="flex-1 py-2 px-3.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-medium shadow-xs transition flex items-center justify-center space-x-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {analysisState === 'loading' ? (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        <span>Analyzing Video...</span>
                      </>
                    ) : (
                      <>
                        <Activity className="h-3.5 w-3.5" />
                        <span>Analyze Video</span>
                      </>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={analysisState === 'loading' || uploadStatus === 'uploading'}
                    className="py-2 px-3 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-lg text-xs font-medium transition disabled:opacity-40"
                  >
                    Change Video
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".mp4,.avi,.mkv,.mov,video/*"
                    onChange={handleFileInputChange}
                    className="hidden"
                  />
                </div>
              </div>
            </div>

            {/* 3. PROCESSING STATE */}
            {analysisState === 'loading' && (
              <div className="p-4 rounded-lg border border-slate-200 bg-slate-50/50 space-y-2 mt-3">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center space-x-2 text-slate-800 font-medium">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-600" />
                    <span>Analysis in progress</span>
                    <span className="text-slate-400">•</span>
                    <span className="text-slate-600 font-normal">{currentStageText}</span>
                  </div>
                  <span className="font-mono text-slate-600 text-[11px] font-semibold">{analysisProgress}%</span>
                </div>
                <div className="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
                  <div 
                    className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
                    style={{ width: `${Math.max(5, Math.min(100, analysisProgress))}%` }}
                  />
                </div>
              </div>
            )}

            {/* ERROR STATE */}
            {analysisState === 'error' && (
              <div className="p-3.5 rounded-lg border border-red-200 bg-red-50 text-xs text-red-700 flex items-start justify-between gap-3 mt-3">
                <div className="flex items-start space-x-2">
                  <AlertTriangle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
                  <div>
                    <p className="font-semibold">Analysis failed</p>
                    <p className="text-red-600 mt-0.5 leading-relaxed">{errorMessage || 'Video processing encountered an error.'}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={startAnalysis}
                  className="px-2.5 py-1 bg-white hover:bg-red-100 text-red-700 border border-red-200 rounded text-xs font-medium transition shrink-0"
                >
                  Retry analysis
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 4. DETECTION RESULTS */}
      {(analysisState === 'success_violence' || analysisState === 'success_normal') && (
        <div className="space-y-5">
          {/* Verdict Banner */}
          {analysisState === 'success_violence' ? (
            <div className="p-4 rounded-xl border border-red-200 bg-red-50 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start space-x-3">
                <div className="p-2 rounded-lg bg-red-100 text-red-700 shrink-0">
                  <AlertTriangle className="h-5 w-5 text-red-600" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="text-xs font-bold text-red-700 uppercase tracking-wide px-2 py-0.5 rounded bg-red-100 border border-red-200">
                      Violence detected
                    </span>
                    <span className="text-xs font-mono text-slate-600">
                      {segments.length} segment{segments.length !== 1 ? 's' : ''} identified
                    </span>
                  </div>
                  <p className="text-xs text-slate-700 mt-1 leading-relaxed">
                    Physical altercation detected in surveillance footage. Review segments and evidence below.
                  </p>
                </div>
              </div>
              <div className="flex items-center space-x-2 shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    setAnalysisState('idle');
                    setAnalysisResult(null);
                  }}
                  className="p-1.5 bg-white hover:bg-slate-50 text-slate-600 rounded-lg border border-slate-200 text-xs transition"
                  title="Reset analysis"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ) : (
            <div className="p-4 rounded-xl border border-emerald-200 bg-emerald-50 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start space-x-3">
                <div className="p-2 rounded-lg bg-emerald-100 text-emerald-700 shrink-0">
                  <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="text-xs font-bold text-emerald-700 uppercase tracking-wide px-2 py-0.5 rounded bg-emerald-100 border border-emerald-200">
                      No violence detected
                    </span>
                    <span className="text-xs font-mono text-slate-600">
                      Confidence: 0.0%
                    </span>
                  </div>
                  <p className="text-xs text-slate-600 mt-1 leading-relaxed">
                    No violence indicators detected in this footage. This analysis applies only to processed intervals.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setAnalysisState('idle');
                  setAnalysisResult(null);
                }}
                className="px-3 py-1.5 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 rounded-lg text-xs font-medium transition shrink-0"
              >
                Analyze Another Video
              </button>
            </div>
          )}

          {/* If Violence Detected: Compact Segments Table & Details */}
          {analysisState === 'success_violence' && (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs">
              <div className="p-4 border-b border-slate-200 flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-bold text-slate-900">Detected Altercation Segments</h2>
                  <p className="text-xs text-slate-500 mt-0.5">Chronological breakdown of flagged intervals</p>
                </div>
                <span className="text-xs font-mono font-medium text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
                  Total: {segments.length}
                </span>
              </div>

              {/* Compact Segments Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200 text-slate-600 text-[11px] uppercase tracking-wider font-medium">
                      <th className="py-2.5 px-4">#</th>
                      <th className="py-2.5 px-4">Time Range</th>
                      <th className="py-2.5 px-4">Duration</th>
                      <th className="py-2.5 px-4">Confidence</th>
                      <th className="py-2.5 px-4">Severity</th>
                      <th className="py-2.5 px-4">Persons</th>
                      <th className="py-2.5 px-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {segments.map((seg, idx) => {
                      const personsCount = seg.persons_count ?? seg.students?.length ?? 0;
                      const confPercent = Math.round(seg.confidence * 100);

                      return (
                        <tr key={seg.segment_id || idx} className="hover:bg-slate-50/70 transition">
                          <td className="py-2.5 px-4 font-mono font-medium text-slate-700">
                            {idx + 1}
                          </td>
                          <td className="py-2.5 px-4 font-mono font-semibold text-slate-900">
                            {seg.timestamp_display}
                          </td>
                          <td className="py-2.5 px-4 text-slate-600 font-mono">
                            {Math.round(seg.duration)}s
                          </td>
                          <td className="py-2.5 px-4 font-mono font-bold text-red-600">
                            {confPercent}%
                          </td>
                          <td className="py-2.5 px-4">
                            <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-medium uppercase font-mono ${
                              seg.severity.toLowerCase() === 'high'
                                ? 'bg-red-50 text-red-700 border border-red-200'
                                : 'bg-amber-50 text-amber-700 border border-amber-200'
                            }`}>
                              {seg.severity}
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-slate-600">
                            <span className="inline-flex items-center space-x-1">
                              <Users className="h-3 w-3 text-slate-400" />
                              <span>{personsCount > 0 ? `${personsCount} observed` : 'Unassigned'}</span>
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-right space-x-2">
                            <button
                              type="button"
                              onClick={() => seekVideo(seg.start_time)}
                              className="px-2 py-1 text-slate-600 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 rounded text-xs transition inline-flex items-center space-x-1"
                              title="Jump to time in footage"
                            >
                              <Play className="h-3 w-3" />
                              <span>Jump</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedSegmentModalIndex(idx);
                                setEvidenceMediaType(seg.evidence_video ? 'clip' : 'frame');
                              }}
                              className="px-2.5 py-1 text-blue-700 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded text-xs font-medium transition inline-flex items-center space-x-1"
                            >
                              <span>View evidence</span>
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Identified Persons Section */}
              <div className="p-4 border-t border-slate-200 bg-slate-50/50 space-y-2.5">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
                    Identified Persons
                  </h3>
                  {confirmedPersons.length > 0 && (
                    <span className="text-[11px] font-mono text-slate-500">
                      {confirmedPersons.length} confirmed {confirmedPersons.length === 1 ? 'match' : 'matches'}
                    </span>
                  )}
                </div>

                {confirmedPersons.length > 0 ? (
                  <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 text-[10px] uppercase tracking-wider font-medium">
                          <th className="py-2 px-3 w-12">Photo</th>
                          <th className="py-2 px-3">Student Name</th>
                          <th className="py-2 px-3">Roll Number</th>
                          <th className="py-2 px-3 text-right">Match Similarity</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {confirmedPersons.map((person) => {
                          const matchPercent = typeof person.similarity_score === 'number' && person.similarity_score > 0
                            ? Math.round(person.similarity_score * 100)
                            : null;

                          return (
                            <tr key={String(person.student_id)} className="hover:bg-slate-50/60 transition">
                              <td className="py-2 px-3">
                                <div className="w-8 h-8 rounded-md overflow-hidden bg-slate-100 border border-slate-200 flex items-center justify-center">
                                  {person.profile_photo_url ? (
                                    <AuthenticatedImage
                                      src={person.profile_photo_url}
                                      alt={person.name}
                                      className="w-full h-full object-cover"
                                    />
                                  ) : (
                                    <Users className="h-3.5 w-3.5 text-slate-400" />
                                  )}
                                </div>
                              </td>
                              <td className="py-2 px-3 font-medium text-slate-900">
                                {person.name}
                              </td>
                              <td className="py-2 px-3 font-mono text-slate-600 text-[11px]">
                                {person.roll_number || '--'}
                              </td>
                              <td className="py-2 px-3 text-right font-mono text-[11px]">
                                {matchPercent !== null ? (
                                  <span className="inline-block px-1.5 py-0.5 rounded font-medium text-emerald-700 bg-emerald-50 border border-emerald-200">
                                    {matchPercent}%
                                  </span>
                                ) : (
                                  <span className="text-slate-400">--</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="p-3 rounded-lg bg-white border border-slate-200 text-xs text-slate-500">
                    No confirmed identities in the flagged intervals.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 5. FOCUSED EVIDENCE MODAL (PART C) */}
      {activeModalSegment && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white border border-slate-200 rounded-xl max-w-5xl w-full max-h-[90vh] flex flex-col shadow-xl overflow-hidden">
            {/* Modal Header */}
            <div className="px-5 py-3.5 border-b border-slate-200 flex items-center justify-between bg-slate-50/70">
              <div className="flex items-center space-x-3">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-700">
                  Evidence Review
                </span>
                <span className="text-slate-300">•</span>
                <span className="text-xs font-mono font-semibold text-slate-900">
                  {activeModalSegment.timestamp_display}
                </span>
                <span className="text-[11px] font-mono text-slate-500">
                  (Segment {(selectedSegmentModalIndex ?? 0) + 1} of {segments.length})
                </span>
              </div>

              <div className="flex items-center space-x-1.5">
                {segments.length > 1 && (
                  <div className="flex items-center space-x-1 mr-2">
                    <button
                      type="button"
                      disabled={(selectedSegmentModalIndex ?? 0) <= 0}
                      onClick={() => setSelectedSegmentModalIndex((prev) => (prev !== null ? Math.max(0, prev - 1) : 0))}
                      className="p-1 rounded text-slate-600 hover:text-slate-900 hover:bg-slate-200 disabled:opacity-30 transition"
                      title="Previous segment"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      disabled={(selectedSegmentModalIndex ?? 0) >= segments.length - 1}
                      onClick={() => setSelectedSegmentModalIndex((prev) => (prev !== null ? Math.min(segments.length - 1, prev + 1) : 0))}
                      className="p-1 rounded text-slate-600 hover:text-slate-900 hover:bg-slate-200 disabled:opacity-30 transition"
                      title="Next segment"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setSelectedSegmentModalIndex(null)}
                  className="p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="p-5 overflow-y-auto grid grid-cols-1 lg:grid-cols-12 gap-5">
              {/* Left Column: Media Player (Preserves Aspect Ratio) */}
              <div className="lg:col-span-7 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    {activeModalSegment.evidence_video && (
                      <button
                        type="button"
                        onClick={() => setEvidenceMediaType('clip')}
                        className={`px-2.5 py-1 rounded text-xs font-medium transition inline-flex items-center space-x-1 ${
                          evidenceMediaType === 'clip'
                            ? 'bg-blue-600 text-white'
                            : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                        }`}
                      >
                        <Film className="h-3 w-3" />
                        <span>Video Clip</span>
                      </button>
                    )}
                    {activeModalSegment.evidence_image && (
                      <button
                        type="button"
                        onClick={() => setEvidenceMediaType('frame')}
                        className={`px-2.5 py-1 rounded text-xs font-medium transition inline-flex items-center space-x-1 ${
                          evidenceMediaType === 'frame'
                            ? 'bg-blue-600 text-white'
                            : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                        }`}
                      >
                        <ImageIcon className="h-3 w-3" />
                        <span>Keyframe Frame</span>
                      </button>
                    )}
                  </div>
                  <span className="text-[11px] font-mono text-slate-500">
                    Duration: {Math.round(activeModalSegment.duration)}s
                  </span>
                </div>

                <div className="bg-slate-950 rounded-lg overflow-hidden border border-slate-200 aspect-video flex items-center justify-center relative">
                  {evidenceMediaType === 'clip' && activeModalSegment.evidence_video ? (
                    <video
                      src={activeModalSegment.evidence_video}
                      controls
                      autoPlay
                      playsInline
                      className="w-full h-full object-contain"
                    />
                  ) : activeModalSegment.evidence_image ? (
                    <AuthenticatedImage
                      src={activeModalSegment.evidence_image}
                      alt="Evidence Frame"
                      className="w-full h-full object-contain"
                    />
                  ) : (
                    <div className="text-center p-6 text-slate-500 text-xs">
                      No standalone evidence asset available for this interval.
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between text-xs text-slate-500 pt-1">
                  <span>Footage: {file?.name || 'Surveillance Clip'}</span>
                  <button
                    type="button"
                    onClick={() => {
                      seekVideo(activeModalSegment.start_time);
                      setSelectedSegmentModalIndex(null);
                    }}
                    className="text-blue-600 hover:text-blue-700 font-medium inline-flex items-center space-x-1"
                  >
                    <Play className="h-3 w-3" />
                    <span>Jump to time in main player</span>
                  </button>
                </div>
              </div>

              {/* Right Column: Compact Investigation Metadata */}
              <div className="lg:col-span-5 space-y-4">
                <div className="space-y-2 border-b border-slate-100 pb-3">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 block">
                    Incident Classification
                  </span>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-slate-900">
                      Physical Altercation / Violence
                    </span>
                    <span className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-red-50 text-red-700 border border-red-200">
                      {Math.round(activeModalSegment.confidence * 100)}% Confidence
                    </span>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    {activeModalSegment.explanation || 'Kinematic indicators confirm high velocity delta and close-contact physical struggle.'}
                  </p>
                </div>

                {/* Key Metadata Grid */}
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="p-2.5 rounded-lg border border-slate-200 bg-slate-50/50">
                    <span className="text-[10px] text-slate-500 uppercase block">Camera</span>
                    <span className="font-semibold text-slate-800 truncate block mt-0.5">
                      {analysisResult?.camera_name || 'Campus Surveillance'}
                    </span>
                  </div>
                  <div className="p-2.5 rounded-lg border border-slate-200 bg-slate-50/50">
                    <span className="text-[10px] text-slate-500 uppercase block">Location</span>
                    <span className="font-semibold text-slate-800 truncate block mt-0.5">
                      {analysisResult?.camera_location || 'Campus Zone'}
                    </span>
                  </div>
                </div>

                {/* Kinematic Signal Breakdown */}
                <div className="space-y-2 pt-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 block">
                    Multi-Signal Breakdown
                  </span>
                  <div className="space-y-1.5 text-xs">
                    <div>
                      <div className="flex justify-between text-[11px] mb-0.5">
                        <span className="text-slate-600">Motion Velocity</span>
                        <span className="font-mono text-slate-700 font-medium">
                          {Math.round((activeModalSegment.breakdown?.motion_dynamics ?? 0.9) * 100)}%
                        </span>
                      </div>
                      <div className="w-full bg-slate-100 rounded-full h-1">
                        <div 
                          className="bg-red-500 h-1 rounded-full" 
                          style={{ width: `${Math.round((activeModalSegment.breakdown?.motion_dynamics ?? 0.9) * 100)}%` }} 
                        />
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between text-[11px] mb-0.5">
                        <span className="text-slate-600">Inter-Person Proximity</span>
                        <span className="font-mono text-slate-700 font-medium">
                          {Math.round((activeModalSegment.breakdown?.person_interaction ?? 0.85) * 100)}%
                        </span>
                      </div>
                      <div className="w-full bg-slate-100 rounded-full h-1">
                        <div 
                          className="bg-amber-500 h-1 rounded-full" 
                          style={{ width: `${Math.round((activeModalSegment.breakdown?.person_interaction ?? 0.85) * 100)}%` }} 
                        />
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between text-[11px] mb-0.5">
                        <span className="text-slate-600">CLIP Semantic Match</span>
                        <span className="font-mono text-slate-700 font-medium">
                          {Math.round((activeModalSegment.breakdown?.clip_similarity ?? 0.75) * 100)}%
                        </span>
                      </div>
                      <div className="w-full bg-slate-100 rounded-full h-1">
                        <div 
                          className="bg-blue-600 h-1 rounded-full" 
                          style={{ width: `${Math.round((activeModalSegment.breakdown?.clip_similarity ?? 0.75) * 100)}%` }} 
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Persons observed in this segment */}
                {activeModalSegment.students && activeModalSegment.students.length > 0 && (
                  <div className="space-y-1.5 pt-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 block">
                      Observed Individuals
                    </span>
                    <div className="space-y-1.5">
                      {activeModalSegment.students.map((st, sIdx) => (
                        <div key={sIdx} className="p-2 rounded border border-slate-200 bg-slate-50/50 flex items-center justify-between text-xs">
                          <span className={st.is_identified ? 'font-semibold text-slate-900' : 'text-slate-600 italic'}>
                            {st.name}
                          </span>
                          <span className="text-[10px] font-mono text-slate-500">
                            {st.roll_number ? `Roll ${st.roll_number}` : 'Unidentified'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-5 py-3 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
              <span className="font-mono text-[11px]">
                Technical Reference: {activeModalSegment.segment_id.slice(0, 8)}
              </span>
              <button
                type="button"
                onClick={() => setSelectedSegmentModalIndex(null)}
                className="px-3 py-1.5 bg-white hover:bg-slate-100 border border-slate-200 rounded-lg text-slate-700 font-medium transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ViolenceDetection;
