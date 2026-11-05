import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '../services/api';
import { SearchBar } from '../components/SearchBar';
import { 
  RefreshCw, 
  ShieldAlert, 
  Eye, 
  Clock, 
  User, 
  AlertTriangle,
  ChevronDown,
  Trash2,
  ExternalLink,
  Film,
  Camera as CameraIcon,
  CameraOff
} from 'lucide-react';
import { DeleteConfirmationModal } from '../components/DeleteConfirmationModal';
import { AuthenticatedImage } from '../components/AuthenticatedImage';

export const Search: React.FC = () => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [selectedResult, setSelectedResult] = useState<any>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<string>('all');
  const [expandedDiagnostics, setExpandedDiagnostics] = useState<Record<string, boolean>>({});

  // Fetch cameras list
  const { data: cameras } = useQuery({
    queryKey: ['cameras-list'],
    queryFn: async () => {
      const response = await api.get('/cameras');
      return Array.isArray(response.data) ? response.data : (response.data.items || []);
    }
  });

  // Unified Search Query Mutation
  const searchMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/investigations/search', {
        query,
        camera_id: selectedCameraId === 'all' ? null : selectedCameraId
      });
      return response.data;
    },
    onSuccess: (data) => {
      if (data?.results?.length > 0) {
        setSelectedResult(data.results[0]);
      } else {
        setSelectedResult(null);
      }
    }
  });

  const [isEvidenceDeleteModalOpen, setIsEvidenceDeleteModalOpen] = useState(false);
  const [evidenceToDeleteId, setEvidenceToDeleteId] = useState<string | null>(null);

  const deleteEvidenceMutation = useMutation({
    mutationFn: async (evidenceId: string) => {
      await api.delete(`/evidence/${evidenceId}`);
    },
    onSuccess: () => {
      if (selectedResult && selectedResult.evidence) {
        const updatedEvidence = { ...selectedResult.evidence, image: null, image_id: null };
        setSelectedResult({
          ...selectedResult,
          evidence: updatedEvidence
        });
      }
      setIsEvidenceDeleteModalOpen(false);
      setEvidenceToDeleteId(null);
      alert('Evidence screenshot deleted successfully!');
    },
    onError: (err: any) => {
      alert(`Failed to delete evidence: ${err.response?.data?.detail || err.message}`);
      setIsEvidenceDeleteModalOpen(false);
      setEvidenceToDeleteId(null);
    }
  });

  const handleSearch = () => {
    if (!query) return;
    searchMutation.mutate();
  };

  const toggleDiagnostic = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedDiagnostics(prev => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  const queryType = searchMutation.data?.query_type || null;
  const rawResults = searchMutation.data?.results || [];

  // Deduplicate repeated matches:
  // For person search (identity/appearance): group repeated detections of the same verified student
  // within the same source video and camera, showing only the earliest valid detection.
  // For incident search: collapse duplicate candidates for the same incident while keeping separate incidents distinct.
  const deduplicatedResults: any[] = React.useMemo(() => {
    if (!rawResults || rawResults.length === 0) return [];

    if (queryType === 'identity' || queryType === 'appearance') {
      const personGrouped = new Map<string, any>();
      for (const res of rawResults) {
        const student = res.student || (res.students && res.students[0]);
        const studentId = student?.id || student?.student_id;
        const vid = res.video_id || res.source_video || 'unknown_video';
        const cam = res.camera_name || res.camera || 'unknown_cam';
        const trackId = res.track_id || res.id || '';

        if (studentId) {
          // Keep distinct tracks/timestamps distinct; if same track repeated, keep earliest
          const key = `student_${studentId}_${vid}_${cam}_${trackId}`;
          if (personGrouped.has(key)) {
            const existing = personGrouped.get(key);
            const existingTime = existing.first_detection_timestamp || existing.detected_at || existing.timestamp || '';
            const newTime = res.first_detection_timestamp || res.detected_at || res.timestamp || '';
            if (newTime && (!existingTime || newTime < existingTime)) {
              personGrouped.set(key, res);
            }
          } else {
            personGrouped.set(key, res);
          }
        } else {
          // Unknown person: preserve separate tracks/identities
          const trackKey = `track_${trackId}_${vid}_${cam}`;
          personGrouped.set(trackKey, res);
        }
      }
      return Array.from(personGrouped.values());
    }

    // Incident search queries: continue grouping duplicate retrieval candidates by stable incident/event ID,
    // while preserving distinct incidents even when they occur close together.
    const grouped = new Map<string, any>();
    for (const res of rawResults) {
      const vid = res.source_video || null;
      const cam = res.camera_name || res.camera || '';
      const start = res.detected_at || res.start_time || res.timestamp || '';
      const itype = res.incident_type || '';
      const incId = res.id || res.incident_id;

      const fullKey = incId ? `inc_${incId}` : `${vid}_${cam}_${start}_${itype}`;
      const baseKey = `${cam}_${start}_${itype}`;

      let matchedKey: string | null = null;
      if (incId) {
        matchedKey = fullKey;
      } else if (!vid) {
        // check if baseKey matches an existing item
        for (const k of grouped.keys()) {
          if (k.endsWith(`_${baseKey}`)) {
            matchedKey = k;
            break;
          }
        }
      } else {
        // if this item has a real video, check if there's an orphan None item to remove
        const orphanKey = `null_${baseKey}`;
        if (grouped.has(orphanKey)) {
          grouped.delete(orphanKey);
        }
        matchedKey = fullKey;
      }

      if (matchedKey && grouped.has(matchedKey)) {
        const existing = grouped.get(matchedKey);
        if (!existing.source_video && res.source_video) {
          grouped.set(matchedKey, res);
        } else if ((res.students?.length || 0) > (existing.students?.length || 0)) {
          grouped.set(matchedKey, res);
        }
      } else {
        grouped.set(matchedKey || fullKey, res);
      }
    }
    return Array.from(grouped.values());
  }, [rawResults, queryType]);

  const getQueryTypeBadge = (type: string) => {
    switch (type) {
      case 'identity':
        return 'bg-blue-50 border-blue-200 text-blue-700';
      case 'appearance':
        return 'bg-purple-50 border-purple-200 text-purple-700';
      case 'incident':
        return 'bg-red-50 border-red-200 text-red-700';
      default:
        return 'bg-slate-100 border-slate-200 text-slate-600';
    }
  };

  const formatAcademicLine = (std: any) => {
    const parts: string[] = [];
    if (std.class || std.programme) parts.push(std.class || std.programme);
    if (std.department && std.department !== 'Not available') parts.push(std.department);
    if (std.semester) parts.push(`Sem ${std.semester}`);
    if (std.year) parts.push(`Year ${std.year}`);
    if (std.section && std.section !== 'Not available') parts.push(`Sec ${std.section}`);
    return parts.join(' • ');
  };

  return (
    <div className="space-y-8 py-2">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-slate-900">AI Investigation Assistant</h2>
        <p className="text-slate-500 text-sm">Search by incident type, student identity, or visual appearance with automated forensic evidence extraction.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left column - search input and results list */}
        <div className="lg:col-span-7 space-y-6">
          {/* Camera Selector */}
          <div className="flex flex-col space-y-1.5 bg-slate-50 p-4 rounded-xl border border-slate-200">
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-600 font-mono">
              Investigation Camera Scope
            </label>
            <select
              value={selectedCameraId}
              onChange={(e) => setSelectedCameraId(e.target.value)}
              className="bg-white border border-slate-300 text-slate-800 text-xs rounded-xl px-4 py-2.5 outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition cursor-pointer max-w-md font-semibold"
            >
              <option value="all">All Cameras</option>
              {cameras?.map((cam: any) => (
                <option key={cam.id} value={cam.id}>
                  {cam.name} ({cam.location})
                </option>
              ))}
            </select>
          </div>

          <div className="flex gap-4">
            <div className="flex-1">
              <SearchBar
                placeholder="Ask anything: 'Fight', 'Find Anukutty', 'person in black shirt'..."
                value={query}
                onChange={setQuery}
                onSubmit={handleSearch}
              />
            </div>
            <button
              onClick={handleSearch}
              disabled={searchMutation.isPending}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-100 disabled:text-slate-400 text-white font-semibold px-6 py-3 rounded-xl shadow-sm transition flex items-center space-x-2"
            >
              {searchMutation.isPending ? (
                <RefreshCw className="h-5 w-5 animate-spin" />
              ) : (
                <span>Analyze</span>
              )}
            </button>
          </div>

          {/* Connection errors */}
          {searchMutation.isError && (
            <div className="flex items-center space-x-3 bg-red-50 border border-red-200 text-red-600 p-4 rounded-xl text-sm">
              <AlertTriangle className="h-5 w-5 flex-shrink-0" />
              <span>Failed to execute search. Check connection to the backend service.</span>
            </div>
          )}

          {/* Idle state */}
          {searchMutation.isIdle && (
            <div className="text-center py-24 text-slate-500 text-sm bg-white border border-slate-200 rounded-2xl shadow-sm">
              Enter any investigation query above to query CCTV records.
            </div>
          )}

          {/* Pending state */}
          {searchMutation.isPending && (
            <div className="text-center py-24 text-slate-400 text-sm animate-pulse bg-white border border-slate-200 rounded-2xl shadow-sm">
              Analyzing visual feeds, incident records, and student biometric registry...
            </div>
          )}

          {/* Results list */}
          {searchMutation.isSuccess && (
            <div className="space-y-4">
              {/* Classified Intent Pill Badge */}
              {queryType && (
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Classification Intent:</span>
                    <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${getQueryTypeBadge(queryType)}`}>
                      {queryType} Search
                    </span>
                  </div>
                  <span className="text-xs text-slate-500 font-medium">
                    {deduplicatedResults.length} {queryType === 'incident' ? 'distinct incident' : 'search result'}{deduplicatedResults.length === 1 ? '' : 's'}
                  </span>
                </div>
              )}

              {deduplicatedResults.length > 0 ? (
                deduplicatedResults.map((res: any, idx: number) => {
                  const cardStudents = res.students && res.students.length > 0 ? res.students : (res.student ? [res.student] : []);
                  const isViolence = (res.incident_type || '').toLowerCase().includes('violence') || (res.incident_type || '').toLowerCase().includes('fight');
                  const isStudentIdentified = (res.incident_type || '').toLowerCase().includes('student') || (res.incident_type || '').toLowerCase().includes('person') || queryType === 'identity';
                  const cardTitle = res.title || (isViolence ? 'Violence detected — Fight' : isStudentIdentified ? (cardStudents[0]?.name ? `Student Identified — ${cardStudents[0].name}` : 'Student Identified') : `${res.incident_type || 'Incident'} detected`);
                  const isSelected = selectedResult === res || (selectedResult && (selectedResult.id === res.id || (selectedResult.incident_id && selectedResult.incident_id === res.incident_id)));
                  const cardKey = res.id || res.incident_id || idx.toString();
                  const showDiag = expandedDiagnostics[cardKey];

                  return (
                    <div
                      key={cardKey}
                      onClick={() => setSelectedResult(res)}
                      className={`bg-white border rounded-2xl p-5 shadow-sm transition cursor-pointer flex flex-col gap-4 ${
                        isSelected ? 'border-blue-500 ring-2 ring-blue-500/10' : 'border-slate-200 hover:border-slate-300'
                      }`}
                    >
                      {/* Top Row: Incident Title & Camera Badge */}
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
                        <div className="flex items-center space-x-2">
                          <span className={`text-xs font-bold px-2.5 py-1 rounded-lg border ${
                            isViolence 
                              ? 'bg-rose-50 text-rose-700 border-rose-200' 
                              : isStudentIdentified
                                ? 'bg-blue-50 text-blue-700 border-blue-200'
                                : 'bg-amber-50 text-amber-700 border-amber-200'
                          }`}>
                            {cardTitle}
                          </span>
                        </div>
                        <div className="flex items-center space-x-1.5 text-xs text-slate-600 font-medium">
                          <CameraIcon className="h-3.5 w-3.5 text-slate-400" />
                          <span>{res.camera_name || res.camera || 'Campus Camera'}</span>
                        </div>
                      </div>

                      {/* Middle Grid: Source Video & Authoritative Start Time */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs bg-slate-50/80 p-3 rounded-xl border border-slate-100">
                        <div>
                          <span className="text-[10px] font-mono uppercase text-slate-500 block">Source Video</span>
                          <span className="font-semibold text-slate-800 break-all flex items-center gap-1 mt-0.5">
                            <Film className="h-3 w-3 text-slate-400 flex-shrink-0" />
                            {res.source_video || 'Source video unavailable'}
                          </span>
                        </div>
                        <div>
                          <span className="text-[10px] font-mono uppercase text-slate-500 block">
                            {queryType === 'identity' || queryType === 'appearance' ? 'First Detection' : 'Detected at (Start)'}
                          </span>
                          <span className="font-bold text-slate-900 flex items-center gap-1 mt-0.5">
                            <Clock className="h-3 w-3 text-slate-400 flex-shrink-0" />
                            {res.first_detection_timestamp || res.detected_at || res.start_time || res.timestamp || 'Timestamp unavailable'}
                          </span>
                        </div>
                      </div>

                      {/* Identified Students Section */}
                      <div className="space-y-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 font-mono block">
                          Identified Students
                        </span>
                        {cardStudents.length > 0 ? (
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {cardStudents.map((std: any, sIdx: number) => (
                              <div
                                key={sIdx}
                                className="flex items-center space-x-3 bg-white p-2.5 rounded-xl border border-slate-200 shadow-2xs"
                              >
                                {std.photo_url ? (
                                  <div className="w-10 h-10 rounded-lg overflow-hidden flex-shrink-0 border border-slate-200 bg-slate-100">
                                    <AuthenticatedImage
                                      src={std.photo_url}
                                      alt={std.name}
                                      className="w-full h-full object-cover"
                                      fallbackIcon={<User className="h-5 w-5 text-slate-400 m-auto" />}
                                    />
                                  </div>
                                ) : (
                                  <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center flex-shrink-0 font-bold text-xs border border-blue-100">
                                    {std.name?.slice(0, 2)?.toUpperCase() || 'ST'}
                                  </div>
                                )}
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between">
                                    <span className="text-xs font-bold text-slate-900 truncate">{std.name}</span>
                                    <span className="text-[10px] text-blue-700 bg-blue-50 px-1.5 py-0.2 rounded font-mono font-semibold">
                                      {std.roll_number || 'N/A'}
                                    </span>
                                  </div>
                                  <p className="text-[11px] text-slate-500 truncate mt-0.5">
                                    {formatAcademicLine(std) || 'Student Record Verified'}
                                  </p>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-xs text-slate-400 italic bg-slate-50/50 p-2.5 rounded-xl border border-dashed border-slate-200 text-center">
                            No confirmed student identities
                          </div>
                        )}
                      </div>

                      {/* Evidence Screenshot Thumbnail & View Incident Button */}
                      <div className="flex items-center justify-between pt-2 border-t border-slate-100 gap-3">
                        <div className="flex items-center space-x-2">
                          {res.evidence?.image || res.evidence?.person_crop ? (
                            <div className="flex items-center space-x-2">
                              <div className="w-12 h-10 rounded-lg overflow-hidden border border-slate-200 bg-slate-100 flex-shrink-0 flex items-center justify-center">
                                <AuthenticatedImage
                                  src={res.evidence.image || res.evidence.person_crop}
                                  alt="Evidence thumbnail"
                                  className="w-full h-full object-contain"
                                  fallbackIcon={<Eye className="h-4 w-4 text-slate-400 m-auto" />}
                                />
                              </div>
                              <span className="text-[11px] text-slate-500 font-medium">
                                {res.evidence.image ? 'Full Evidence' : 'Person Crop'}
                              </span>
                            </div>
                          ) : (
                            <span className="text-[11px] text-slate-400">No screenshot thumbnail</span>
                          )}
                        </div>

                        <div className="flex items-center space-x-2">
                          <button
                            type="button"
                            onClick={(e) => toggleDiagnostic(cardKey, e)}
                            className="text-[11px] text-slate-500 hover:text-slate-700 px-2.5 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 transition flex items-center space-x-1"
                          >
                            <span>Diagnostics</span>
                            <ChevronDown className={`h-3 w-3 transition-transform ${showDiag ? 'rotate-180' : ''}`} />
                          </button>

                          {(res.incident_id || (!['Student Identified', 'Appearance Match'].includes(res.incident_type) && typeof res.id === 'string' && !res.id.startsWith('identity_') && !res.id.startsWith('appearance_') && res.id)) && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                navigate(`/events/${res.incident_id || res.id}`);
                              }}
                              className="bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-3.5 py-1.5 rounded-xl shadow-2xs transition flex items-center space-x-1.5"
                            >
                              <span>View Incident</span>
                              <ExternalLink className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Expandable Diagnostics Details */}
                      {showDiag && (
                        <div className="bg-slate-50 p-3 rounded-xl border border-slate-200 text-[11px] text-slate-600 space-y-1.5 font-mono">
                          <div className="flex justify-between">
                            <span className="text-slate-400">Match Reason:</span>
                            <span className="text-slate-700 font-sans text-right max-w-xs">{res.match_reason}</span>
                          </div>
                          {res.confidence !== undefined && (
                            <div className="flex justify-between">
                              <span className="text-slate-400">Confidence Score:</span>
                              <span className="font-bold text-slate-800">{(res.confidence * 100).toFixed(1)}%</span>
                            </div>
                          )}
                          {res.incident_interval && (
                            <div className="flex justify-between">
                              <span className="text-slate-400">Detection Interval:</span>
                              <span className="text-slate-700">{res.incident_interval}</span>
                            </div>
                          )}
                          {res.id && (
                            <div className="flex justify-between">
                              <span className="text-slate-400">Record ID:</span>
                              <span className="text-slate-700">{res.id}</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              ) : (
                <div className="text-center py-16 text-slate-500 text-sm bg-white border border-slate-200 rounded-2xl shadow-sm">
                  No records matched your search query. Try: "Fight", "Find Anukutty", or "person in black shirt".
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right column - simplified forensic evidence dossier */}
        <div className="lg:col-span-5">
          {selectedResult ? (
            <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-6">
              {/* Header: Incident Type & View Incident action */}
              <div className="flex items-center justify-between border-b border-slate-200 pb-3">
                <div className="flex items-center space-x-2">
                  <ShieldAlert className="h-5 w-5 text-blue-600" />
                  <span className="font-bold text-slate-900 text-sm">
                    {selectedResult.title || (
                      (selectedResult.incident_type || '').toLowerCase().includes('violence') || (selectedResult.incident_type || '').toLowerCase().includes('fight')
                        ? 'Violence detected — Fight'
                        : `${selectedResult.incident_type || 'Incident'} detected`
                    )}
                  </span>
                </div>
                {(selectedResult.incident_id || (!['Student Identified', 'Appearance Match'].includes(selectedResult.incident_type) && typeof selectedResult.id === 'string' && !selectedResult.id.startsWith('identity_') && !selectedResult.id.startsWith('appearance_') && selectedResult.id)) && (
                  <button
                    type="button"
                    onClick={() => navigate(`/events/${selectedResult.incident_id || selectedResult.id}`)}
                    className="text-xs font-semibold text-blue-600 hover:text-blue-700 flex items-center space-x-1"
                  >
                    <span>View Incident</span>
                    <ExternalLink className="h-3 w-3" />
                  </button>
                )}
              </div>

              {/* Incident Metadata (Source Video, Camera, Incident Start Timestamp) */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 space-y-2.5 text-xs">
                <div>
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">Source Video</span>
                  <span className="font-semibold text-slate-800 break-all flex items-center gap-1.5 mt-0.5">
                    <Film className="h-3.5 w-3.5 text-slate-400 flex-shrink-0" />
                    {selectedResult.source_video || 'Source video unavailable'}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-200/60">
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">Camera</span>
                    <span className="font-semibold text-slate-800 flex items-center gap-1 mt-0.5">
                      <CameraIcon className="h-3 w-3 text-slate-400 flex-shrink-0" />
                      {selectedResult.camera_name || selectedResult.camera || 'Campus Camera'}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">Detected At (Start)</span>
                    <span className="font-bold text-slate-900 flex items-center gap-1 mt-0.5">
                      <Clock className="h-3 w-3 text-slate-400 flex-shrink-0" />
                      {selectedResult.detected_at || selectedResult.start_time || selectedResult.timestamp || 'Timestamp unavailable'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Confirmed Student Details */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold text-slate-600 uppercase tracking-wider block font-mono">
                    Confirmed Student Details
                  </span>
                  {selectedResult.students && selectedResult.students.length > 0 && (
                    <span className="text-[10px] text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200 font-mono font-semibold">
                      {selectedResult.students.length} Verified in Directory
                    </span>
                  )}
                </div>

                {selectedResult.students && selectedResult.students.length > 0 ? (
                  selectedResult.students.map((std: any, sIdx: number) => (
                    <div key={sIdx} className="bg-slate-50 border border-slate-200 p-4 rounded-xl space-y-3">
                      <div className="flex items-center space-x-3 border-b border-slate-200 pb-3">
                        {std.photo_url ? (
                          <div className="w-12 h-12 rounded-xl overflow-hidden border border-slate-200 bg-white flex-shrink-0">
                            <AuthenticatedImage
                              src={std.photo_url}
                              alt={std.name}
                              className="w-full h-full object-cover"
                              fallbackIcon={<User className="h-6 w-6 text-slate-400 m-auto" />}
                            />
                          </div>
                        ) : (
                          <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-700 flex items-center justify-center flex-shrink-0 font-bold text-sm">
                            {std.name?.slice(0, 2)?.toUpperCase() || 'ST'}
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <h4 className="text-sm font-bold text-slate-900 truncate">{std.name}</h4>
                          <span className="text-xs font-mono font-semibold text-blue-600">
                            Roll No: {std.roll_number || 'N/A'}
                          </span>
                        </div>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-3 text-xs text-slate-600">
                        <div>
                          <span className="text-[9px] text-slate-500 uppercase font-mono block">Class / Programme</span>
                          <span className="text-slate-800 font-semibold">{std.class || std.programme || 'Not available'}</span>
                        </div>
                        <div>
                          <span className="text-[9px] text-slate-500 uppercase font-mono block">Department</span>
                          <span className="text-slate-800 font-semibold">{std.department || 'Not available'}</span>
                        </div>
                        <div>
                          <span className="text-[9px] text-slate-500 uppercase font-mono block">Semester & Year</span>
                          <span className="text-slate-800 font-semibold">
                            {[std.semester ? `Sem ${std.semester}` : null, std.year ? `Year ${std.year}` : null].filter(Boolean).join(', ') || 'Not available'}
                          </span>
                        </div>
                        <div>
                          <span className="text-[9px] text-slate-500 uppercase font-mono block">Section</span>
                          <span className="text-slate-800 font-semibold">{std.section || 'Not available'}</span>
                        </div>
                      </div>
                    </div>
                  ))
                ) : selectedResult.student ? (
                  <div className="bg-slate-50 border border-slate-200 p-4 rounded-xl space-y-3">
                    <div className="flex items-center space-x-3 border-b border-slate-200 pb-3">
                      {selectedResult.student.photo_url ? (
                        <div className="w-12 h-12 rounded-xl overflow-hidden border border-slate-200 bg-white flex-shrink-0">
                          <AuthenticatedImage
                            src={selectedResult.student.photo_url}
                            alt={selectedResult.student.name}
                            className="w-full h-full object-cover"
                            fallbackIcon={<User className="h-6 w-6 text-slate-400 m-auto" />}
                          />
                        </div>
                      ) : (
                        <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-700 flex items-center justify-center flex-shrink-0 font-bold text-sm">
                          {selectedResult.student.name?.slice(0, 2)?.toUpperCase() || 'ST'}
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        <h4 className="text-sm font-bold text-slate-900 truncate">{selectedResult.student.name}</h4>
                        <span className="text-xs font-mono font-semibold text-blue-600">
                          Roll No: {selectedResult.student.roll_number || 'N/A'}
                        </span>
                      </div>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-3 text-xs text-slate-600">
                      <div>
                        <span className="text-[9px] text-slate-500 uppercase font-mono block">Class / Programme</span>
                        <span className="text-slate-800 font-semibold">{selectedResult.student.class || selectedResult.student.programme || 'Not available'}</span>
                      </div>
                      <div>
                        <span className="text-[9px] text-slate-500 uppercase font-mono block">Department</span>
                        <span className="text-slate-800 font-semibold">{selectedResult.student.department || 'Not available'}</span>
                      </div>
                      <div>
                        <span className="text-[9px] text-slate-500 uppercase font-mono block">Semester & Year</span>
                        <span className="text-slate-800 font-semibold">
                          {[selectedResult.student.semester ? `Sem ${selectedResult.student.semester}` : null, selectedResult.student.year ? `Year ${selectedResult.student.year}` : null].filter(Boolean).join(', ') || 'Not available'}
                        </span>
                      </div>
                      <div>
                        <span className="text-[9px] text-slate-500 uppercase font-mono block">Section</span>
                        <span className="text-slate-800 font-semibold">{selectedResult.student.section || 'Not available'}</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-5 bg-slate-50 border border-dashed border-slate-200 text-xs text-slate-400 rounded-xl">
                    No confirmed student identities
                  </div>
                )}
              </div>

              {/* Evidence Screenshot & Person Crop Presentation */}
              <div className="space-y-3">
                <div className="flex items-center justify-between text-[10px] font-bold text-slate-500 uppercase font-mono">
                  <div className="flex items-center space-x-1.5">
                    <Eye className="h-3.5 w-3.5 text-blue-600" />
                    <span>Evidence Screenshot</span>
                    {selectedResult.evidence?.is_nearby ? (
                      <span className="text-[9px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200 font-semibold normal-case">
                        Nearby Frame
                      </span>
                    ) : selectedResult.evidence?.image ? (
                      <span className="text-[9px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200 font-semibold normal-case">
                        Verified Detection Frame
                      </span>
                    ) : null}
                  </div>
                  {selectedResult.evidence?.image_id && (
                    <button
                      onClick={() => {
                        setEvidenceToDeleteId(selectedResult.evidence.image_id);
                        setIsEvidenceDeleteModalOpen(true);
                      }}
                      className="text-red-600 hover:text-red-700 transition flex items-center space-x-1 font-semibold"
                      title="Delete Screenshot"
                    >
                      <Trash2 className="h-3 w-3" />
                      <span>Delete</span>
                    </button>
                  )}
                </div>

                {/* Full Evidence Frame Container */}
                <div className="border border-slate-200 rounded-xl overflow-hidden bg-slate-900/5 min-h-[220px] max-h-72 flex items-center justify-center p-2">
                  {selectedResult.evidence?.image ? (
                    <AuthenticatedImage
                      src={selectedResult.evidence.image}
                      alt="Incident Evidence Screenshot"
                      className="max-h-64 w-auto max-w-full object-contain rounded-lg shadow-2xs"
                      fallbackIcon={
                        <div className="flex flex-col items-center justify-center text-slate-400 p-6 space-y-1.5 text-center">
                          <CameraOff className="h-8 w-8 text-slate-300 mx-auto" />
                          <span className="text-xs font-semibold text-slate-600">Evidence unavailable</span>
                          <span className="text-[10px] text-slate-400">File not found or unreadable</span>
                        </div>
                      }
                    />
                  ) : (
                    <div className="flex flex-col items-center justify-center text-slate-400 p-8 space-y-1.5 text-center">
                      <CameraOff className="h-8 w-8 text-slate-300 mx-auto" />
                      <span className="text-xs font-semibold text-slate-600">Evidence unavailable</span>
                      <span className="text-[10px] text-slate-400">No evidence screenshot recorded for this detection</span>
                    </div>
                  )}
                </div>

                {/* Separate Companion Person Crop if Available */}
                {selectedResult.evidence?.person_crop && (
                  <div className="flex items-center space-x-3 bg-slate-50 border border-slate-200 p-2.5 rounded-xl">
                    <div className="w-12 h-14 rounded-lg overflow-hidden border border-slate-200 bg-white flex-shrink-0 flex items-center justify-center">
                      <AuthenticatedImage
                        src={selectedResult.evidence.person_crop}
                        alt="Detected Person Crop"
                        className="w-full h-full object-contain"
                        fallbackIcon={<User className="h-5 w-5 text-slate-300" />}
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block font-mono">
                        Person Crop
                      </span>
                      <span className="text-xs text-slate-700 font-medium">
                        Cropped detection view of the subject
                      </span>
                    </div>
                  </div>
                )}
              </div>

              {/* View Incident Link Button */}
              {(selectedResult.incident_id || (!['Student Identified', 'Appearance Match'].includes(selectedResult.incident_type) && typeof selectedResult.id === 'string' && !selectedResult.id.startsWith('identity_') && !selectedResult.id.startsWith('appearance_') && selectedResult.id)) && (
                <div className="pt-2">
                  <button
                    type="button"
                    onClick={() => navigate(`/events/${selectedResult.incident_id || selectedResult.id}`)}
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-4 rounded-xl shadow-sm transition flex items-center justify-center space-x-2 text-sm"
                  >
                    <span>View Incident</span>
                    <ExternalLink className="h-4 w-4" />
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-24 text-slate-400 text-xs border border-dashed border-slate-200 rounded-2xl bg-white shadow-sm">
              Select an incident from the search results to inspect its evidence details.
            </div>
          )}
        </div>
      </div>

      <DeleteConfirmationModal
        isOpen={isEvidenceDeleteModalOpen}
        onClose={() => { setIsEvidenceDeleteModalOpen(false); setEvidenceToDeleteId(null); }}
        onConfirm={() => { if (evidenceToDeleteId) deleteEvidenceMutation.mutate(evidenceToDeleteId); }}
        title="Delete Evidence Screenshot"
        message="Are you sure you want to permanently delete this evidence screenshot? This action is irreversible."
        isLoading={deleteEvidenceMutation.isPending}
      />
    </div>
  );
};

export default Search;
