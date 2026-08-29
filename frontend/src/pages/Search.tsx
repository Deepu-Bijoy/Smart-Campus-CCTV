import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '../services/api';
import { SearchBar } from '../components/SearchBar';
import { 
  RefreshCw, 
  ShieldAlert, 
  Video, 
  Eye, 
  Calendar, 
  User, 
  FileText, 
  Download, 
  AlertTriangle,
  Clock,
  ExternalLink,
  ChevronRight,
  Trash2
} from 'lucide-react';
import { DeleteConfirmationModal } from '../components/DeleteConfirmationModal';

export const Search: React.FC = () => {
  const [query, setQuery] = useState('');
  const [selectedResult, setSelectedResult] = useState<any>(null);
  const [selectedCameraId, setSelectedCameraId] = useState<string>('all');

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
  const [evidenceTypeToDelete, setEvidenceTypeToDelete] = useState<'image' | 'video' | null>(null);

  const deleteEvidenceMutation = useMutation({
    mutationFn: async (evidenceId: string) => {
      await api.delete(`/evidence/${evidenceId}`);
    },
    onSuccess: () => {
      if (selectedResult && selectedResult.evidence) {
        const updatedEvidence = { ...selectedResult.evidence };
        if (evidenceTypeToDelete === 'image') {
          updatedEvidence.image = null;
          updatedEvidence.image_id = null;
        } else if (evidenceTypeToDelete === 'video') {
          updatedEvidence.video = null;
          updatedEvidence.video_id = null;
        }
        setSelectedResult({
          ...selectedResult,
          evidence: updatedEvidence
        });
      }
      setIsEvidenceDeleteModalOpen(false);
      setEvidenceToDeleteId(null);
      setEvidenceTypeToDelete(null);
      alert('Evidence file deleted successfully!');
    },
    onError: (err: any) => {
      alert(`Failed to delete evidence: ${err.response?.data?.detail || err.message}`);
      setIsEvidenceDeleteModalOpen(false);
      setEvidenceToDeleteId(null);
      setEvidenceTypeToDelete(null);
    }
  });

  const handleSearch = () => {
    if (!query) return;
    searchMutation.mutate();
  };

  const queryType = searchMutation.data?.query_type || null;
  const results = searchMutation.data?.results || [];

  const getQueryTypeBadge = (type: string) => {
    switch (type) {
      case 'identity':
        return 'bg-blue-600/10 border-blue-500/20 text-blue-400';
      case 'appearance':
        return 'bg-purple-600/10 border-purple-500/20 text-purple-400';
      case 'incident':
        return 'bg-red-600/10 border-red-500/20 text-red-400';
      default:
        return 'bg-slate-800 border-slate-700 text-slate-400';
    }
  };

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  return (
    <div className="space-y-8 py-2">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-slate-100">AI Investigation Assistant</h2>
        <p className="text-slate-400 text-sm">One search bar for all incident, biometric student name, or clothing appearance queries.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left column - search input and results list */}
        <div className="lg:col-span-7 space-y-6">
          {/* Camera Selector */}
          <div className="flex flex-col space-y-1.5 bg-slate-900/40 p-4 rounded-xl border border-dark-border">
            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 font-mono">
              Investigation Camera Scope
            </label>
            <select
              value={selectedCameraId}
              onChange={(e) => setSelectedCameraId(e.target.value)}
              className="bg-dark-card border border-dark-border text-slate-200 text-xs rounded-xl px-4 py-2.5 outline-none focus:border-blue-500 transition cursor-pointer max-w-md font-semibold"
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
                placeholder="Ask anything: 'Find Dipz', 'person in black shirt', 'Did anyone jump the wall?'..."
                value={query}
                onChange={setQuery}
                onSubmit={handleSearch}
              />
            </div>
            <button
              onClick={handleSearch}
              disabled={searchMutation.isPending}
              className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white font-semibold px-6 py-3 rounded-xl shadow-lg transition flex items-center space-x-2"
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
            <div className="flex items-center space-x-3 bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-xl text-sm">
              <AlertTriangle className="h-5 w-5 flex-shrink-0" />
              <span>Failed to execute search. Check connection to the backend service.</span>
            </div>
          )}

          {/* Loading, Empty and Success states */}
          {searchMutation.isIdle && (
            <div className="text-center py-24 text-slate-500 text-sm bg-dark-card border border-dark-border rounded-2xl">
              Enter any investigation query above to query the CCTV logs.
            </div>
          )}

          {searchMutation.isPending && (
            <div className="text-center py-24 text-slate-400 text-sm animate-pulse bg-dark-card border border-dark-border rounded-2xl">
              Classifying search intent and routing query through visual networks...
            </div>
          )}

          {searchMutation.isSuccess && (
            <div className="space-y-4">
              
              {/* Classified Intent Pill Badge */}
              {queryType && (
                <div className="flex items-center space-x-2">
                  <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Classification Intent:</span>
                  <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${getQueryTypeBadge(queryType)}`}>
                    {queryType} Search
                  </span>
                </div>
              )}

              {results.length > 0 ? (
                results.map((res: any, idx: number) => (
                  <div
                    key={idx}
                    onClick={() => setSelectedResult(res)}
                    className={`bg-dark-card border rounded-2xl p-5 shadow-md transition cursor-pointer flex flex-col md:flex-row md:items-center justify-between gap-4 ${
                      selectedResult === res ? 'border-blue-500 ring-2 ring-blue-500/10' : 'border-dark-border hover:border-slate-700'
                    }`}
                  >
                    <div className="space-y-3 flex-1">
                      <div className="flex items-center space-x-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/50">
                          Match #{idx + 1}
                        </span>
                        <span className="text-[10px] font-semibold text-slate-500 font-mono">
                          Camera: {res.camera}
                        </span>
                      </div>
                      
                      {/* Explainability reason */}
                      <p className="text-xs text-slate-300 font-medium">
                        {res.match_reason}
                      </p>

                      <div className="flex items-center space-x-4 text-[10px] text-slate-500 font-mono">
                        <span className="flex items-center space-x-1">
                          <Calendar className="h-3 w-3" />
                          <span>{res.timestamp}</span>
                        </span>
                        {res.student && (
                          <span className="flex items-center space-x-1 text-blue-400 font-semibold">
                            <User className="h-3 w-3" />
                            <span>{res.student.name}</span>
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center space-x-2 justify-end">
                      <span className="text-xs font-bold text-slate-400">
                        Score: {res.confidence.toFixed(2)}
                      </span>
                      <ChevronRight className="h-5 w-5 text-slate-600" />
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-16 text-slate-500 text-sm bg-dark-card border border-dark-border rounded-2xl">
                  No records matched your search query. Try: "Find Dipz", "person in black shirt", or "Did anyone jump the wall?".
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right column - detailed forensic evidence dossiers */}
        <div className="lg:col-span-5">
          {selectedResult ? (
            <div className="bg-dark-card border border-dark-border rounded-2xl p-6 shadow-xl space-y-6">
              <div className="flex items-center justify-between border-b border-dark-border pb-3">
                <div className="flex items-center space-x-2 text-slate-200 font-bold">
                  <ShieldAlert className="h-5 w-5 text-blue-500" />
                  <span>Forensic Evidence Dossier</span>
                </div>
              </div>

              {/* General Metadata */}
              <div className="grid grid-cols-2 gap-4 bg-slate-900/40 p-4 rounded-xl border border-dark-border/50 text-xs">
                <div>
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">Camera Name</span>
                  <span className="font-semibold text-slate-200">{selectedResult.camera}</span>
                </div>
                <div>
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">Search Confidence</span>
                  <span className="font-bold text-blue-400 font-mono">
                    {(selectedResult.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="mt-2">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">Timestamp</span>
                  <span className="font-semibold text-slate-200">{selectedResult.timestamp}</span>
                </div>
                <div className="mt-2">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-mono">Match Routing</span>
                  <span className="font-semibold text-slate-400 capitalize">{queryType} Pipeline</span>
                </div>
              </div>

              {/* Explainable Match Reason */}
              <div className="space-y-2">
                <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider block font-mono">Reason for Match</span>
                <div className="bg-slate-900/60 border border-dark-border p-4 rounded-xl text-xs text-slate-300 italic leading-relaxed">
                  "{selectedResult.match_reason}"
                </div>
              </div>

              {/* Involved Student Card */}
              <div className="space-y-3">
                <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider block font-mono">
                  Involved Engaged Student Profile(s)
                </span>
                {selectedResult.students && selectedResult.students.length > 0 ? (
                  selectedResult.students.map((std: any, sIdx: number) => (
                    <div key={sIdx} className="bg-slate-900/40 border border-dark-border p-4 rounded-xl space-y-3">
                      <div className="flex justify-between items-center border-b border-dark-border/40 pb-2">
                        <div className="flex items-center space-x-2">
                          <User className="h-4 w-4 text-blue-400" />
                          <span className="text-xs font-bold text-slate-200">{std.name}</span>
                        </div>
                        <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-mono font-semibold">
                          Identified in Directory
                        </span>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-3 text-[11px] text-slate-400 font-mono">
                        <div>
                          <span className="text-[9px] text-slate-500 block">Roll Number</span>
                          <span className="text-slate-300 font-bold">{std.roll_number}</span>
                        </div>
                        <div>
                          <span className="text-[9px] text-slate-500 block">Class / Section</span>
                          <span className="text-slate-300 font-bold">{std.class}</span>
                        </div>
                      </div>
                    </div>
                  ))
                ) : selectedResult.student ? (
                  <div className="bg-slate-900/40 border border-dark-border p-4 rounded-xl space-y-3">
                    <div className="flex justify-between items-center border-b border-dark-border/40 pb-2">
                      <div className="flex items-center space-x-2">
                        <User className="h-4 w-4 text-blue-400" />
                        <span className="text-xs font-bold text-slate-200">{selectedResult.student.name}</span>
                      </div>
                      <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-mono font-semibold">
                        Identified in Directory
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-3 text-[11px] text-slate-400 font-mono">
                      <div>
                        <span className="text-[9px] text-slate-500 block">Roll Number</span>
                        <span className="text-slate-300 font-bold">{selectedResult.student.roll_number}</span>
                      </div>
                      <div>
                        <span className="text-[9px] text-slate-500 block">Class / Section</span>
                        <span className="text-slate-300 font-bold">{selectedResult.student.class}</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-6 bg-slate-900/30 border border-dashed border-dark-border text-xs text-slate-500 rounded-xl">
                    No matching student identified in face registry database. (Unknown Person)
                  </div>
                )}
              </div>

              {/* Evidence visuals */}
              <div className="space-y-4">
                <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider block font-mono">Evidence Visuals</span>
                <div className="grid grid-cols-1 gap-4 font-mono">
                  {/* Screenshot frame */}
                  {selectedResult.evidence?.image && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-[10px] font-bold text-slate-400 uppercase">
                        <div className="flex items-center space-x-1">
                          <Eye className="h-3 w-3" />
                          <span>Screenshot Crop Preview</span>
                        </div>
                        {selectedResult.evidence.image_id && (
                          <button
                            onClick={() => {
                              setEvidenceToDeleteId(selectedResult.evidence.image_id);
                              setEvidenceTypeToDelete('image');
                              setIsEvidenceDeleteModalOpen(true);
                            }}
                            className="text-red-500 hover:text-red-400 transition flex items-center space-x-1 font-semibold"
                            title="Delete Screenshot"
                          >
                            <Trash2 className="h-3 w-3" />
                            <span>Delete</span>
                          </button>
                        )}
                      </div>
                      <div className="border border-dark-border rounded-xl overflow-hidden bg-slate-950 flex justify-center">
                        <img
                          src={`${API_URL}${selectedResult.evidence.image}`}
                          alt="Screenshot Crop"
                          className="max-h-48 object-contain"
                          onError={(e: any) => {
                            e.target.src = '/storage/crops/simulated_face.jpg';
                          }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Video clip */}
                  {selectedResult.evidence?.video && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-[10px] font-bold text-slate-400 uppercase">
                        <div className="flex items-center space-x-1">
                          <Video className="h-3 w-3" />
                          <span>Video Clip Recording</span>
                        </div>
                        {selectedResult.evidence.video_id && (
                          <button
                            onClick={() => {
                              setEvidenceToDeleteId(selectedResult.evidence.video_id);
                              setEvidenceTypeToDelete('video');
                              setIsEvidenceDeleteModalOpen(true);
                            }}
                            className="text-red-500 hover:text-red-400 transition flex items-center space-x-1 font-semibold"
                            title="Delete Video Clip"
                          >
                            <Trash2 className="h-3 w-3" />
                            <span>Delete</span>
                          </button>
                        )}
                      </div>
                      <div className="border border-dark-border rounded-xl overflow-hidden bg-slate-950">
                        <video
                          src={`${API_URL}${selectedResult.evidence.video}`}
                          controls
                          className="w-full max-h-48 object-contain"
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center py-24 text-slate-500 text-xs border border-dashed border-dark-border rounded-2xl bg-dark-card/50">
              Select a search result item from the listing to view its detailed forensic evidence dossier.
            </div>
          )}
        </div>
      </div>

      <DeleteConfirmationModal
        isOpen={isEvidenceDeleteModalOpen}
        onClose={() => { setIsEvidenceDeleteModalOpen(false); setEvidenceToDeleteId(null); setEvidenceTypeToDelete(null); }}
        onConfirm={() => { if (evidenceToDeleteId) deleteEvidenceMutation.mutate(evidenceToDeleteId); }}
        title="Delete Forensic Evidence"
        message="Are you sure you want to permanently delete this evidence file? This action is irreversible."
        isLoading={deleteEvidenceMutation.isPending}
      />
    </div>
  );
};
export default Search;
