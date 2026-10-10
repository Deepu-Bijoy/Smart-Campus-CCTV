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
    <div className="bg-white border border-slate-200 rounded-xl p-5 hover:border-blue-500/50 hover:shadow-md transition duration-300 shadow-sm flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="bg-blue-50 p-3 rounded-xl border border-blue-100">
            <User className="h-6 w-6 text-blue-600" />
          </div>
        </div>
        <h3 className="font-semibold text-slate-900 text-lg mb-1">{student.name}</h3>
        <p className="text-sm text-slate-500 font-mono mb-4">{student.university_roll_number}</p>
        
        <div className="space-y-2 mb-6">
          <div className="flex items-center text-xs text-slate-600 space-x-2">
            <Award className="h-4 w-4 text-slate-400" />
            <span>{student.department}</span>
          </div>
          <div className="flex items-center text-xs text-slate-600 space-x-2">
            <Shield className="h-4 w-4 text-slate-400" />
            <span>{student.programme} — Year {student.year}</span>
          </div>
        </div>
      </div>
      
      <Link
        to={`/students/${student.id}`}
        className="w-full text-center block py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium transition"
      >
        View Profile
      </Link>
    </div>
  );
};
