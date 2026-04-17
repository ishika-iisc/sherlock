import React from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Upload from './pages/Upload';
import Documents from './pages/Documents';
import DocumentDetail from './pages/DocumentDetail';
import Search from './pages/Search';

const navItems = [
  { path: '/', label: '📊 Dashboard' },
  { path: '/upload', label: '📤 Upload' },
  { path: '/documents', label: '📄 Documents' },
  { path: '/search', label: '🔍 Search' },
];

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <nav className="sidebar">
          <h1>📑 Doc Intelligence</h1>
          {navItems.map(({ path, label }) => (
            <NavLink key={path} to={path} className={({ isActive }) => isActive ? 'active' : ''} end>
              {label}
            </NavLink>
          ))}
        </nav>
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/documents" element={<Documents />} />
            <Route path="/documents/:id" element={<DocumentDetail />} />
            <Route path="/search" element={<Search />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
