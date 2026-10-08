import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { Image as ImageIcon } from 'lucide-react';

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

    let isMounted = true;
    let createdUrl: string | null = null;
    setLoading(true);
    setError(false);

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

    api.get(targetUrl, { responseType: 'blob' })
      .then((res) => {
        if (!isMounted) return;
        createdUrl = window.URL.createObjectURL(res.data);
        setObjectUrl(createdUrl);
        setLoading(false);
      })
      .catch((err) => {
        if (!isMounted) return;
        console.error('Failed to load authenticated image asset:', err);
        setError(true);
        setLoading(false);
      });

    return () => {
      isMounted = false;
      if (createdUrl) {
        window.URL.revokeObjectURL(createdUrl);
      }
    };
  }, [src]);

  if (loading) {
    return (
      <div className={`flex items-center justify-center bg-slate-900/60 animate-pulse ${className}`}>
        <span className="text-[10px] text-slate-500 font-mono">Loading...</span>
      </div>
    );
  }

  if (error || !objectUrl) {
    return (
      <div className={`flex items-center justify-center bg-slate-900 text-slate-600 ${className}`}>
        {fallbackIcon || <ImageIcon className="h-6 w-6 text-slate-600" />}
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
