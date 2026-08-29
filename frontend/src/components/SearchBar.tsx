import React from 'react';
import { Search } from 'lucide-react';

interface SearchBarProps {
  placeholder?: string;
  value: string;
  onChange: (v: string) => void;
  onSubmit?: () => void;
}

export const SearchBar: React.FC<SearchBarProps> = ({ placeholder = "Search...", value, onChange, onSubmit }) => {
  return (
    <div className="relative flex items-center w-full">
      <Search className="absolute left-4 h-5 w-5 text-slate-400" />
      <input
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && onSubmit && onSubmit()}
        className="w-full pl-12 pr-4 py-3 bg-dark-card border border-dark-border rounded-xl text-slate-100 placeholder-slate-400 focus:outline-none focus:border-blue-500 transition shadow-lg"
      />
    </div>
  );
};
