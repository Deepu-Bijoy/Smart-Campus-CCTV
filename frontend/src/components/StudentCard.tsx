import React from 'react';
import { Link } from 'react-router-dom';
import { User, Award, Shield } from 'lucide-react';

export interface StudentData {
  id: string;
  name: string;
  university_roll_number: string;
  department: string;
  programme: string;
  year: number;
  status: string;
}

interface StudentCardProps {
  student: StudentData;
}

export const StudentCard: React.FC<StudentCardProps> = ({ student }) => {
  return (
    <div className="bg-dark-card border border-dark-border rounded-xl p-5 hover:border-blue-500/50 transition duration-300 shadow-md hover:shadow-lg flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="bg-blue-600/10 p-3 rounded-xl border border-blue-500/20">
            <User className="h-6 w-6 text-blue-500" />
          </div>
          <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
            student.status === 'active' 
              ? 'bg-green-500/10 text-green-500 border-green-500/20' 
              : 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20'
          }`}>
            {student.status}
          </span>
        </div>
        <h3 className="font-semibold text-slate-100 text-lg mb-1">{student.name}</h3>
        <p className="text-sm text-slate-400 font-mono mb-4">{student.university_roll_number}</p>
        
        <div className="space-y-2 mb-6">
          <div className="flex items-center text-xs text-slate-400 space-x-2">
            <Award className="h-4 w-4 text-slate-500" />
            <span>{student.department}</span>
          </div>
          <div className="flex items-center text-xs text-slate-400 space-x-2">
            <Shield className="h-4 w-4 text-slate-500" />
            <span>{student.programme} — Year {student.year}</span>
          </div>
        </div>
      </div>
      
      <Link
        to={`/students/${student.id}`}
        className="w-full text-center block py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white rounded-lg text-sm font-medium transition"
      >
        View Profile
      </Link>
    </div>
  );
};
