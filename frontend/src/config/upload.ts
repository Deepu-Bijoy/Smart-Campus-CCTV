import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';

// Configurable maximum upload size (default: 5 GiB = 5,368,709,120 bytes)
export const DEFAULT_MAX_UPLOAD_SIZE_BYTES = 
  Number(import.meta.env.VITE_MAX_UPLOAD_SIZE_BYTES) || 5368709120;

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) {
    const gib = bytes / (1024 * 1024 * 1024);
    return `${Number.isInteger(gib) ? gib : gib.toFixed(1)} GiB`;
  }
  if (bytes >= 1024 * 1024) {
    const mib = bytes / (1024 * 1024);
    return `${Number.isInteger(mib) ? mib : mib.toFixed(1)} MiB`;
  }
  return `${bytes} B`;
}

export interface UploadConfig {
  max_upload_size_bytes: number;
  max_upload_size_formatted: string;
  allowed_formats: string[];
}

export function useUploadConfig() {
  return useQuery<UploadConfig>({
    queryKey: ['video-upload-config'],
    queryFn: async () => {
      try {
        const res = await api.get('/videos/upload-config');
        return res.data;
      } catch {
        return {
          max_upload_size_bytes: DEFAULT_MAX_UPLOAD_SIZE_BYTES,
          max_upload_size_formatted: formatBytes(DEFAULT_MAX_UPLOAD_SIZE_BYTES),
          allowed_formats: ['MP4', 'AVI', 'MKV', 'MOV'],
        };
      }
    },
    initialData: {
      max_upload_size_bytes: DEFAULT_MAX_UPLOAD_SIZE_BYTES,
      max_upload_size_formatted: formatBytes(DEFAULT_MAX_UPLOAD_SIZE_BYTES),
      allowed_formats: ['MP4', 'AVI', 'MKV', 'MOV'],
    },
    staleTime: 60000,
  });
}
