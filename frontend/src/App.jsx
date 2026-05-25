import React, { useState, useEffect } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

function App() {
  // Navigation & Tenant
  const [tenants, setTenants] = useState([]);
  const [activeTenantId, setActiveTenantId] = useState('');
  const [activeTab, setActiveTab] = useState('dashboard'); // 'dashboard', 'queue', 'batches'
  
  // Data Lists
  const [records, setRecords] = useState([]);
  const [batches, setBatches] = useState([]);
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [auditHistory, setAuditHistory] = useState([]);

  // Queue Filters
  const [filterStatus, setFilterStatus] = useState('ALL'); // 'ALL', 'PENDING', 'APPROVED', 'REJECTED', 'SUSPICIOUS', 'FAILED'
  const [filterScope, setFilterScope] = useState('ALL');
  const [filterSourceType, setFilterSourceType] = useState('ALL');

  // Ingestion Form State
  const [uploadSourceType, setUploadSourceType] = useState('SAP_FUEL');
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadJsonData, setUploadJsonData] = useState('');
  const [uploadMsg, setUploadMsg] = useState({ text: '', isError: false });
  const [isUploading, setIsUploading] = useState(false);

  // Edit Modal State
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editForm, setEditForm] = useState({
    category: '',
    activity_date: '',
    original_value: '',
    original_unit: '',
    normalized_value: '',
    normalized_unit: '',
    comment: ''
  });
  const [editError, setEditError] = useState('');

  // General Comments
  const [actionComment, setActionComment] = useState('');

  // Fetch initial Tenants
  useEffect(() => {
    fetch(`${API_BASE}/tenants/`)
      .then(res => res.json())
      .then(data => {
        setTenants(data);
        if (data.length > 0) {
          setActiveTenantId(data[0].id);
        }
      })
      .catch(err => console.error("Error fetching tenants:", err));
  }, []);

  // Fetch batch and records when tenant or filters change
  useEffect(() => {
    if (!activeTenantId) return;
    fetchBatches();
    fetchRecords();
  }, [activeTenantId, filterStatus, filterScope, filterSourceType]);

  // Fetch audit history when a record is selected
  useEffect(() => {
    if (!selectedRecord) {
      setAuditHistory([]);
      return;
    }
    fetchAuditHistory(selectedRecord.id);
  }, [selectedRecord]);

  const fetchBatches = () => {
    fetch(`${API_BASE}/batches/?tenant=${activeTenantId}`)
      .then(res => res.json())
      .then(data => setBatches(data))
      .catch(err => console.error("Error fetching batches:", err));
  };

  const fetchRecords = () => {
    let url = `${API_BASE}/records/?tenant=${activeTenantId}`;
    
    // Apply filters
    if (filterStatus === 'PENDING') url += '&approval_status=PENDING&validation_failed=false';
    else if (filterStatus === 'APPROVED') url += '&approval_status=APPROVED';
    else if (filterStatus === 'REJECTED') url += '&approval_status=REJECTED';
    else if (filterStatus === 'SUSPICIOUS') url += '&suspicious=true';
    else if (filterStatus === 'FAILED') url += '&validation_failed=true';

    if (filterScope !== 'ALL') url += `&scope=${encodeURIComponent(filterScope)}`;
    if (filterSourceType !== 'ALL') url += `&source_type=${filterSourceType}`;

    fetch(url)
      .then(res => res.json())
      .then(data => {
        setRecords(data);
        // Refresh selected record if it exists in the new list to show updated details
        if (selectedRecord) {
          const updated = data.find(r => r.id === selectedRecord.id);
          if (updated) setSelectedRecord(updated);
        }
      })
      .catch(err => console.error("Error fetching records:", err));
  };

  const fetchAuditHistory = (recordId) => {
    fetch(`${API_BASE}/records/${recordId}/audit_history/`)
      .then(res => res.json())
      .then(data => setAuditHistory(data))
      .catch(err => console.error("Error fetching audit history:", err));
  };

  // Upload/Ingestion submit handler
  const handleUploadSubmit = (e) => {
    e.preventDefault();
    setUploadMsg({ text: '', isError: false });
    setIsUploading(true);

    const formData = new FormData();
    formData.append('tenant', activeTenantId);
    formData.append('source_type', uploadSourceType);

    if (uploadFile) {
      formData.append('file', uploadFile);
    } else if (uploadJsonData.trim()) {
      formData.append('json_data', uploadJsonData);
    } else {
      setUploadMsg({ text: 'Please select a file or input raw JSON data', isError: true });
      setIsUploading(false);
      return;
    }

    fetch(`${API_BASE}/batches/`, {
      method: 'POST',
      body: formData
    })
      .then(async res => {
        const data = await res.json();
        if (res.ok) {
          setUploadMsg({ text: `Ingested successfully! ${data.records_created_count} records created.`, isError: false });
          // Clear inputs
          setUploadFile(null);
          setUploadJsonData('');
          // Reset file input element visually
          const fileInput = document.getElementById('file-input');
          if (fileInput) fileInput.value = '';
          // Refresh data
          fetchBatches();
          fetchRecords();
        } else {
          setUploadMsg({ text: data.error || 'Ingestion failed.', isError: true });
        }
      })
      .catch(err => {
        console.error("Upload error:", err);
        setUploadMsg({ text: 'Network error or server unavailable.', isError: true });
      })
      .finally(() => setIsUploading(false));
  };

  // Approve action
  const handleApprove = () => {
    if (!selectedRecord) return;
    const comment = actionComment.trim() || "Approved by analyst.";

    fetch(`${API_BASE}/records/${selectedRecord.id}/approve/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comment })
    })
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          alert(data.error);
        } else {
          setActionComment('');
          fetchRecords();
        }
      })
      .catch(err => console.error("Error approving:", err));
  };

  // Reject action
  const handleReject = () => {
    if (!selectedRecord) return;
    const comment = actionComment.trim() || "Rejected by analyst.";

    fetch(`${API_BASE}/records/${selectedRecord.id}/reject/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comment })
    })
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          alert(data.error);
        } else {
          setActionComment('');
          fetchRecords();
        }
      })
      .catch(err => console.error("Error rejecting:", err));
  };

  // Edit Modal controls
  const openEditModal = () => {
    if (!selectedRecord) return;
    setEditError('');
    setEditForm({
      category: selectedRecord.category,
      activity_date: selectedRecord.activity_date,
      original_value: selectedRecord.original_value,
      original_unit: selectedRecord.original_unit,
      normalized_value: selectedRecord.normalized_value,
      normalized_unit: selectedRecord.normalized_unit,
      comment: ''
    });
    setIsEditModalOpen(true);
  };

  const handleEditSubmit = (e) => {
    e.preventDefault();
    setEditError('');

    if (!editForm.comment.trim()) {
      setEditError('Audit comment is required for making corrections.');
      return;
    }

    fetch(`${API_BASE}/records/${selectedRecord.id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(editForm)
    })
      .then(async res => {
        const data = await res.json();
        if (res.ok) {
          setIsEditModalOpen(false);
          fetchRecords();
        } else {
          setEditError(data.error || 'Failed to update record.');
        }
      })
      .catch(err => {
        console.error("Edit error:", err);
        setEditError('Network error occurred.');
      });
  };

  // Calculations for dashboard summary metrics
  const activeTenantName = tenants.find(t => t.id === activeTenantId)?.name || 'Loading...';
  
  // Only calculate metrics from successfully normalized records that are not rejected
  const activeRecords = records.filter(r => !r.validation_failed && r.approval_status !== 'REJECTED');
  
  const totalEmissions = activeRecords.reduce((sum, r) => sum + parseFloat(r.co2e_emissions || 0), 0);
  const scope1Emissions = activeRecords.filter(r => r.scope === 'Scope 1').reduce((sum, r) => sum + parseFloat(r.co2e_emissions || 0), 0);
  const scope2Emissions = activeRecords.filter(r => r.scope === 'Scope 2').reduce((sum, r) => sum + parseFloat(r.co2e_emissions || 0), 0);
  const scope3Emissions = activeRecords.filter(r => r.scope === 'Scope 3').reduce((sum, r) => sum + parseFloat(r.co2e_emissions || 0), 0);

  // Status counts (total database count for this tenant)
  const pendingCount = records.filter(r => r.approval_status === 'PENDING' && !r.validation_failed).length;
  const approvedCount = records.filter(r => r.approval_status === 'APPROVED').length;
  const rejectedCount = records.filter(r => r.approval_status === 'REJECTED').length;
  const suspiciousCount = records.filter(r => r.suspicious).length;
  const failedCount = records.filter(r => r.validation_failed).length;

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="logo-container">
          <div className="logo-icon">B</div>
          <div className="logo-text">BreatheESG</div>
        </div>

        <div className="tenant-selector">
          <label htmlFor="tenant-select">Active Client</label>
          <select 
            id="tenant-select"
            className="select-input" 
            value={activeTenantId} 
            onChange={(e) => {
              setActiveTenantId(e.target.value);
              setSelectedRecord(null);
            }}
          >
            {tenants.map(t => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>

        <nav style={{ flexGrow: 1 }}>
          <ul className="nav-menu">
            <li>
              <button 
                className={`nav-item ${activeTab === 'dashboard' ? 'active' : ''}`}
                onClick={() => { setActiveTab('dashboard'); setSelectedRecord(null); }}
                style={{ width: '100%', background: 'none', border: 'none', textAlign: 'left' }}
              >
                📊 Dashboard
              </button>
            </li>
            <li>
              <button 
                className={`nav-item ${activeTab === 'queue' ? 'active' : ''}`}
                onClick={() => { setActiveTab('queue'); }}
                style={{ width: '100%', background: 'none', border: 'none', textAlign: 'left' }}
              >
                🔍 Review Queue
              </button>
            </li>
            <li>
              <button 
                className={`nav-item ${activeTab === 'batches' ? 'active' : ''}`}
                onClick={() => { setActiveTab('batches'); setSelectedRecord(null); }}
                style={{ width: '100%', background: 'none', border: 'none', textAlign: 'left' }}
              >
                📥 Batch Uploads
              </button>
            </li>
          </ul>
        </nav>

        <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border-color)', paddingTop: '16px' }}>
          <div className="user-badge">
            <div className="user-dot"></div>
            <span>Analyst Workspace</span>
          </div>
        </div>
      </aside>

      {/* Main Content Pane */}
      <main className="main-content">
        <header className="header">
          <div className="header-title">
            <h1>{activeTenantName} ESG Dashboard</h1>
          </div>
          <div className="header-meta">
            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>System Time: May 2026</span>
          </div>
        </header>

        <div className="page-body">
          {/* Dashboard Tab */}
          {activeTab === 'dashboard' && (
            <div>
              {/* Summary Cards */}
              <div className="summary-grid">
                <div className="card">
                  <div className="card-title">Total Emissions</div>
                  <div className="card-value" style={{ color: 'var(--color-primary)' }}>
                    {totalEmissions.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                  <div className="card-unit">kg CO2e</div>
                </div>
                <div className="card scope-1">
                  <div className="card-title">Scope 1 (Direct)</div>
                  <div className="card-value" style={{ color: 'var(--color-scope1)' }}>
                    {scope1Emissions.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                  <div className="card-unit">kg CO2e</div>
                </div>
                <div className="card scope-2">
                  <div className="card-title">Scope 2 (Electricity)</div>
                  <div className="card-value" style={{ color: 'var(--color-scope2)' }}>
                    {scope2Emissions.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                  <div className="card-unit">kg CO2e</div>
                </div>
                <div className="card scope-3">
                  <div className="card-title">Scope 3 (Travel)</div>
                  <div className="card-value" style={{ color: 'var(--color-scope3)' }}>
                    {scope3Emissions.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                  <div className="card-unit">kg CO2e</div>
                </div>
              </div>

              <div className="dashboard-layout">
                {/* Workflow summary statistics */}
                <div className="section-card">
                  <h3 className="section-title">Queue Progress Overview</h3>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '16px', textAlign: 'center' }}>
                    <div style={{ padding: '12px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px' }}>
                      <div style={{ fontSize: '1.5rem', fontWeight: '700', color: 'var(--color-pending)' }}>{pendingCount}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>Pending Review</div>
                    </div>
                    <div style={{ padding: '12px', background: 'rgba(16, 185, 129, 0.05)', borderRadius: '8px', border: '1px solid rgba(16, 185, 129, 0.15)' }}>
                      <div style={{ fontSize: '1.5rem', fontWeight: '700', color: 'var(--color-approved)' }}>{approvedCount}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>Approved</div>
                    </div>
                    <div style={{ padding: '12px', background: 'rgba(244, 63, 94, 0.05)', borderRadius: '8px', border: '1px solid rgba(244, 63, 94, 0.15)' }}>
                      <div style={{ fontSize: '1.5rem', fontWeight: '700', color: 'var(--color-rejected)' }}>{rejectedCount}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>Rejected</div>
                    </div>
                    <div style={{ padding: '12px', background: 'rgba(245, 158, 11, 0.05)', borderRadius: '8px', border: '1px solid rgba(245, 158, 11, 0.15)' }}>
                      <div style={{ fontSize: '1.5rem', fontWeight: '700', color: 'var(--color-suspicious)' }}>{suspiciousCount}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>Suspicious Flagged</div>
                    </div>
                    <div style={{ padding: '12px', background: 'rgba(239, 68, 68, 0.05)', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.15)' }}>
                      <div style={{ fontSize: '1.5rem', fontWeight: '700', color: 'var(--color-failed)' }}>{failedCount}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>Failed Validation</div>
                    </div>
                  </div>
                  
                  <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'center' }}>
                    <button className="btn" onClick={() => setActiveTab('queue')}>Go to Review Queue &rarr;</button>
                  </div>
                </div>

                {/* Fast Upload Access */}
                <div className="section-card">
                  <h3 className="section-title">Quick Ingest</h3>
                  <form onSubmit={handleUploadSubmit}>
                    <div className="upload-form-group">
                      <label htmlFor="source-select">Source Type</label>
                      <select 
                        id="source-select"
                        className="select-input" 
                        value={uploadSourceType} 
                        onChange={(e) => setUploadSourceType(e.target.value)}
                      >
                        <option value="SAP_FUEL">SAP Fuel Procurement (CSV)</option>
                        <option value="UTILITY_ELECTRICITY">Utility Electricity Export (CSV)</option>
                        <option value="TRAVEL_JSON">Corporate Travel Flights (JSON)</option>
                      </select>
                    </div>

                    <div className="upload-form-group">
                      <label htmlFor="file-input">Upload CSV or JSON File</label>
                      <input 
                        type="file" 
                        id="file-input" 
                        accept=".csv,.json"
                        style={{ display: 'none' }}
                        onChange={(e) => {
                          setUploadFile(e.target.files[0]);
                          setUploadJsonData('');
                        }}
                      />
                      <div 
                        className="file-dropzone"
                        onClick={() => document.getElementById('file-input').click()}
                      >
                        <p>{uploadFile ? `Selected: ${uploadFile.name}` : "Click to select data file"}</p>
                      </div>
                    </div>

                    <div style={{ textAlign: 'center', margin: '12px 0', color: 'var(--text-muted)', fontSize: '0.8rem' }}>OR paste raw JSON payload below</div>

                    <div className="upload-form-group">
                      <textarea 
                        className="textarea-input"
                        placeholder="[ { ... }, { ... } ]"
                        value={uploadJsonData}
                        onChange={(e) => {
                          setUploadJsonData(e.target.value);
                          setUploadFile(null);
                        }}
                      ></textarea>
                    </div>

                    {uploadMsg.text && (
                      <div className={`alert ${uploadMsg.isError ? 'alert-danger' : 'alert-warning'}`} style={{ borderLeftWidth: '3px' }}>
                        {uploadMsg.text}
                      </div>
                    )}

                    <button 
                      type="submit" 
                      className="btn" 
                      style={{ width: '100%' }}
                      disabled={isUploading}
                    >
                      {isUploading ? "Processing Ingestion..." : "Ingest & Normalize"}
                    </button>
                  </form>
                </div>
              </div>
            </div>
          )}

          {/* Review Queue Tab */}
          {activeTab === 'queue' && (
            <div className="split-layout">
              {/* Left Side: Table List */}
              <div className="left-pane">
                {/* Filters */}
                <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: '600' }}>Filter Status:</span>
                    {['ALL', 'PENDING', 'APPROVED', 'REJECTED', 'SUSPICIOUS', 'FAILED'].map((st) => (
                      <button
                        key={st}
                        className={`filter-badge ${filterStatus === st ? 'active' : ''}`}
                        onClick={() => setFilterStatus(st)}
                      >
                        {st}
                      </button>
                    ))}
                  </div>
                </div>

                <div style={{ marginBottom: '16px', display: 'flex', gap: '20px' }}>
                  <div>
                    <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Scope</label>
                    <select className="select-input" value={filterScope} onChange={(e) => setFilterScope(e.target.value)}>
                      <option value="ALL">All Scopes</option>
                      <option value="Scope 1">Scope 1 - Direct</option>
                      <option value="Scope 2">Scope 2 - Electricity</option>
                      <option value="Scope 3">Scope 3 - Travel</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Source Channel</label>
                    <select className="select-input" value={filterSourceType} onChange={(e) => setFilterSourceType(e.target.value)}>
                      <option value="ALL">All Sources</option>
                      <option value="SAP_FUEL">SAP Fuel Procurement</option>
                      <option value="UTILITY_ELECTRICITY">Utility Electricity</option>
                      <option value="TRAVEL_JSON">Corporate Travel</option>
                    </select>
                  </div>
                </div>

                <div className="table-container">
                  <table className="review-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Scope</th>
                        <th>Category</th>
                        <th>Original Amount</th>
                        <th>Normalized Amount</th>
                        <th>Emissions (kg CO2e)</th>
                        <th>Audit Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.length === 0 ? (
                        <tr>
                          <td colSpan="7" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                            No ESG records match active filters.
                          </td>
                        </tr>
                      ) : (
                        records.map((r) => {
                          let rowClass = "";
                          if (r.validation_failed) rowClass = "row-failed";
                          else if (r.suspicious) rowClass = "row-suspicious";
                          if (selectedRecord && selectedRecord.id === r.id) rowClass += " selected";

                          return (
                            <tr 
                              key={r.id} 
                              className={rowClass}
                              onClick={() => setSelectedRecord(r)}
                            >
                              <td>{r.activity_date}</td>
                              <td>
                                <span className={`badge badge-${r.scope.replace(" ", "").toLowerCase()}`}>
                                  {r.scope}
                                </span>
                              </td>
                              <td>{r.category}</td>
                              <td>{parseFloat(r.original_value).toFixed(2)} {r.original_unit}</td>
                              <td>{parseFloat(r.normalized_value).toFixed(2)} {r.normalized_unit}</td>
                              <td style={{ fontWeight: '600' }}>
                                {r.validation_failed ? "N/A" : parseFloat(r.co2e_emissions).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                              </td>
                              <td>
                                {r.validation_failed ? (
                                  <span className="badge badge-failed">FAIL</span>
                                ) : r.suspicious ? (
                                  <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                                    <span className={`badge badge-${r.approval_status.toLowerCase()}`}>{r.approval_status}</span>
                                    <span className="badge badge-suspicious">SUSP</span>
                                  </div>
                                ) : (
                                  <span className={`badge badge-${r.approval_status.toLowerCase()}`}>{r.approval_status}</span>
                                )}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Right Side: Detail Panel */}
              <div className="right-pane">
                <div className="pane-header">
                  <div className="pane-title">Inspect & Approve</div>
                  {selectedRecord && (
                    <span className={`badge badge-${selectedRecord.approval_status.toLowerCase()}`}>
                      {selectedRecord.is_locked ? "🔒 Locked" : "🔓 Open"}
                    </span>
                  )}
                </div>

                <div className="pane-body">
                  {!selectedRecord ? (
                    <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '40px 0' }}>
                      Select a record from the review table to inspect details, raw source payloads, and audit histories.
                    </div>
                  ) : (
                    <div className="compare-container">
                      {/* Critical Flags / Alerts */}
                      {selectedRecord.validation_failed && (
                        <div className="alert alert-danger">
                          <div className="alert-title">❌ Ingestion Validation Failed</div>
                          <div>Reason: <strong>{selectedRecord.failure_reason}</strong></div>
                          <div style={{ marginTop: '8px', fontSize: '0.75rem' }}>This row failed parsing rules. Modify normalized fields below to resolve the error.</div>
                        </div>
                      )}

                      {selectedRecord.suspicious && (
                        <div className="alert alert-warning">
                          <div className="alert-title">⚠️ Suspicious Activity Warning</div>
                          <ul style={{ margin: '4px 0 0 16px' }}>
                            {selectedRecord.suspicious_reasons.map((reason, i) => (
                              <li key={i}>{reason}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Comparative Side-by-side Layout */}
                      <div className="compare-box">
                        <div className="compare-box-title">Raw Payload Ingested</div>
                        <pre className="pre-payload">
                          {JSON.stringify(selectedRecord.raw_payload, null, 2)}
                        </pre>
                      </div>

                      <div className="compare-box">
                        <div className="compare-box-title">Normalized Data Fields</div>
                        <div className="field-grid">
                          <div className="field-item">
                            <span className="field-label">Scope</span>
                            <span className="field-value">{selectedRecord.scope}</span>
                          </div>
                          <div className="field-item">
                            <span className="field-label">Activity Date</span>
                            <span className="field-value">{selectedRecord.activity_date}</span>
                          </div>
                          <div className="field-item">
                            <span className="field-label">Original Inflow</span>
                            <span className="field-value">{parseFloat(selectedRecord.original_value).toFixed(2)} {selectedRecord.original_unit}</span>
                          </div>
                          <div className="field-item">
                            <span className="field-label">Normalized Activity</span>
                            <span className="field-value">{parseFloat(selectedRecord.normalized_value).toFixed(2)} {selectedRecord.normalized_unit}</span>
                          </div>
                          <div className="field-item" style={{ gridColumn: 'span 2' }}>
                            <span className="field-label">Calculated Climate Impact</span>
                            <span className="field-value" style={{ color: 'var(--color-primary)', fontWeight: '700', fontSize: '1.15rem' }}>
                              {selectedRecord.validation_failed ? "N/A" : `${parseFloat(selectedRecord.co2e_emissions).toLocaleString(undefined, { maximumFractionDigits: 2 })} kg CO2e`}
                            </span>
                          </div>
                          <div className="field-item" style={{ gridColumn: 'span 2' }}>
                            <span className="field-label">Category Name</span>
                            <span className="field-value">{selectedRecord.category}</span>
                          </div>
                        </div>

                        {!selectedRecord.is_locked && (
                          <div style={{ marginTop: '14px', textAlign: 'right' }}>
                            <button className="btn btn-secondary btn-sm" onClick={openEditModal}>✏️ Edit & Correct</button>
                          </div>
                        )}
                      </div>

                      {/* Audit History Timeline */}
                      <div className="compare-box">
                        <div className="compare-box-title">Audit History & Trail</div>
                        {auditHistory.length === 0 ? (
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No audit history records found.</div>
                        ) : (
                          <div className="timeline">
                            {auditHistory.map((log) => (
                              <div key={log.id} className="timeline-item">
                                <div className={`timeline-marker ${log.action}`}></div>
                                <div className="timeline-content">
                                  <div className="timeline-header">
                                    <span className="timeline-user">{log.changed_by_username || "System Ingestion"}</span>
                                    <span className="timeline-action">{log.action}</span>
                                    <span className="timeline-time">{new Date(log.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                                  </div>
                                  {log.comments && <div className="timeline-comment">{log.comments}</div>}
                                  {log.action === 'EDIT' && log.previous_state && log.new_state && (
                                    <div className="timeline-diff">
                                      {Object.keys(log.new_state).map((k) => {
                                        if (log.previous_state[k] !== log.new_state[k]) {
                                          return (
                                            <div key={k}>
                                              &bull; {k}: <span style={{ textDecoration: 'line-through', color: 'var(--color-failed)' }}>{String(log.previous_state[k])}</span> &rarr; <span style={{ color: 'var(--color-approved)' }}>{String(log.new_state[k])}</span>
                                            </div>
                                          );
                                        }
                                        return null;
                                      })}
                                    </div>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Action forms for Approve/Reject */}
                      {!selectedRecord.is_locked && (
                        <div className="compare-box" style={{ background: 'rgba(0, 0, 0, 0.15)' }}>
                          <div className="compare-box-title">Workspace Review Action</div>
                          <textarea
                            className="textarea-input"
                            placeholder="Add action review logs comment (required for auditing)..."
                            style={{ height: '60px', fontSize: '0.8rem', marginBottom: '10px' }}
                            value={actionComment}
                            onChange={(e) => setActionComment(e.target.value)}
                          ></textarea>

                          <div style={{ display: 'flex', gap: '8px' }}>
                            <button 
                              className="btn btn-success" 
                              style={{ flexGrow: 1 }}
                              onClick={handleApprove}
                              disabled={selectedRecord.validation_failed}
                            >
                              ✅ Approve & Lock
                            </button>
                            <button 
                              className="btn btn-danger" 
                              style={{ flexGrow: 1 }}
                              onClick={handleReject}
                            >
                              ❌ Reject Row
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Batch uploads view */}
          {activeTab === 'batches' && (
            <div style={{ maxWidth: '900px' }}>
              <div className="section-card">
                <h3 className="section-title">Ingestion Batches History</h3>
                <div className="table-container">
                  <table className="review-table">
                    <thead>
                      <tr>
                        <th>Batch ID</th>
                        <th>Created Date</th>
                        <th>Channel Type</th>
                        <th>Filename</th>
                        <th>Execution Status</th>
                        <th>Error Logs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batches.length === 0 ? (
                        <tr>
                          <td colSpan="6" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                            No ingestion batches found.
                          </td>
                        </tr>
                      ) : (
                        batches.map((b) => (
                          <tr key={b.id}>
                            <td style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{b.id}</td>
                            <td>{new Date(b.created_at).toLocaleString()}</td>
                            <td>
                              <span className="badge badge-scope2">{b.source_type}</span>
                            </td>
                            <td>{b.filename}</td>
                            <td>
                              <span className={`badge badge-${b.status.toLowerCase()}`}>
                                {b.status}
                              </span>
                            </td>
                            <td style={{ color: 'var(--color-failed)', fontSize: '0.8rem' }}>
                              {b.error_message || "-"}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Edit modal */}
      {isEditModalOpen && (
        <div className="modal-overlay">
          <form className="modal-content" onSubmit={handleEditSubmit}>
            <div className="modal-header">Edit Normalized Activity Record</div>
            
            <div className="modal-body">
              {editError && (
                <div className="alert alert-danger" style={{ marginBottom: '16px' }}>
                  {editError}
                </div>
              )}

              <div className="upload-form-group">
                <label>Category Label</label>
                <input 
                  type="text" 
                  className="input-text"
                  value={editForm.category}
                  onChange={(e) => setEditForm({ ...editForm, category: e.target.value })}
                />
              </div>

              <div className="upload-form-group">
                <label>Activity Date</label>
                <input 
                  type="date" 
                  className="input-text"
                  value={editForm.activity_date}
                  onChange={(e) => setEditForm({ ...editForm, activity_date: e.target.value })}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="upload-form-group">
                  <label>Original Value</label>
                  <input 
                    type="number" 
                    step="0.0001"
                    className="input-text"
                    value={editForm.original_value}
                    onChange={(e) => setEditForm({ ...editForm, original_value: e.target.value })}
                  />
                </div>
                <div className="upload-form-group">
                  <label>Original Unit</label>
                  <input 
                    type="text" 
                    className="input-text"
                    value={editForm.original_unit}
                    onChange={(e) => setEditForm({ ...editForm, original_unit: e.target.value })}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="upload-form-group">
                  <label>Normalized Value</label>
                  <input 
                    type="number" 
                    step="0.0001"
                    className="input-text"
                    value={editForm.normalized_value}
                    onChange={(e) => setEditForm({ ...editForm, normalized_value: e.target.value })}
                  />
                </div>
                <div className="upload-form-group">
                  <label>Normalized Unit</label>
                  <input 
                    type="text" 
                    className="input-text"
                    value={editForm.normalized_unit}
                    onChange={(e) => setEditForm({ ...editForm, normalized_unit: e.target.value })}
                  />
                </div>
              </div>

              <div className="upload-form-group">
                <label>Reason for Modification (Required for Audit Log)*</label>
                <textarea 
                  className="textarea-input"
                  style={{ height: '80px' }}
                  placeholder="e.g. Corrected original unit conversion error from invoice receipts."
                  value={editForm.comment}
                  onChange={(e) => setEditForm({ ...editForm, comment: e.target.value })}
                  required
                ></textarea>
              </div>
            </div>

            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={() => setIsEditModalOpen(false)}>Cancel</button>
              <button type="submit" className="btn">Save & Update</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

export default App;
