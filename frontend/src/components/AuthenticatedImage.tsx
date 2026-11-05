import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { Image as ImageIcon } from 'lucide-react';

// Module-level cache to eliminate repeated network fetches and 404 retries
const failedUrlSet = new Set<string>();
const blobUrlCache = new Map<string, string>();

interface AuthenticatedImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string;
  fallbackIcon?: React.ReactNode;
}

export const AuthenticatedImage: React.FC<AuthenticatedImageProps> = ({
  src,
  alt = '',
  className = '',
  fallbackIcon,
  ...props
}) => {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<boolean>(false);

  useEffect(() => {
    if (!src) {
      setLoading(false);
      setError(true);
      return;
    }

    if (src.startsWith('blob:') || src.startsWith('data:')) {
      setObjectUrl(src);
      setLoading(false);
      return;
    }

    // Normalize path to fetch via authenticated axios client
    let endpoint = src.replace(/\\/g, '/');
    if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
      try {
        const parsed = new URL(endpoint);
        endpoint = parsed.pathname;
      } catch {
        // fallback
      }
    }
    if (!endpoint.startsWith('/')) {
      endpoint = '/' + endpoint;
    }
    endpoint = endpoint.replace(/^\/storage\/storage\//, '/storage/');

    // Determine target URL:
    // If endpoint is /storage/..., prepend root host (strip /api/v1 from baseURL)
    const baseUrlRoot = api.defaults.baseURL ? api.defaults.baseURL.replace(/\/api\/v1\/?$/, '') : 'http://127.0.0.1:8000';
    const targetUrl = endpoint.startsWith('/storage')
      ? `${baseUrlRoot}${endpoint}`
      : `${api.defaults.baseURL || 'http://127.0.0.1:8000/api/v1'}${endpoint}`;

    // 1. If previously confirmed 404 or failed, fail immediately without triggering network requests
    if (failedUrlSet.has(targetUrl)) {
      setError(true);
      setLoading(false);
      return;
    }

    // 2. If cached in blobUrlCache, reuse immediately
    if (blobUrlCache.has(targetUrl)) {
      setObjectUrl(blobUrlCache.get(targetUrl)!);
      setLoading(false);
      setError(false);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError(false);

    api.get(targetUrl, { responseType: 'blob' })
      .then((res) => {
        const createdUrl = window.URL.createObjectURL(res.data);
        blobUrlCache.set(targetUrl, createdUrl);
        if (!isMounted) return;
        setObjectUrl(createdUrl);
        setLoading(false);
      })
      .catch(() => {
        // Register in failed set so future renders never re-request this missing asset
        failedUrlSet.add(targetUrl);
        if (!isMounted) return;
        setError(true);
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [src]);

  if (loading) {
    return (
      <div className={`flex items-center justify-center bg-slate-100 animate-pulse ${className}`}>
        <span className="text-[10px] text-slate-400 font-mono">Loading...</span>
      </div>
    );
  }

  if (error || !objectUrl) {
    return (
      <div className={`flex items-center justify-center bg-slate-100 text-slate-400 ${className}`}>
        {fallbackIcon || <ImageIcon className="h-6 w-6 text-slate-400" />}
      </div>
    );
  }

  return (
    <img
      src={objectUrl}
      alt={alt}
      className={className}
      {...props}
    />
  );
};
