import { useState, useEffect } from 'react';
import { 
  Users, ShoppingBag, Clock, Activity, 
  AlertTriangle, Filter, Map, AlertCircle
} from 'lucide-react';
import './index.css';

const API_BASE = 'https://store-intelligence-api-x283.onrender.com/stores/STORE_BLR_002';

export default function App() {
  const [metrics, setMetrics] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [heatmap, setHeatmap] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [resMetrics, resFunnel, resHeatmap, resAnomalies] = await Promise.all([
          fetch(`${API_BASE}/metrics`).then(res => res.json()),
          fetch(`${API_BASE}/funnel`).then(res => res.json()),
          fetch(`${API_BASE}/heatmap`).then(res => res.json()),
          fetch(`${API_BASE}/anomalies`).then(res => res.json())
        ]);
        
        setMetrics(resMetrics);
        setFunnel(resFunnel);
        setHeatmap(resHeatmap);
        setAnomalies(resAnomalies);
        setError(null);
      } catch (err) {
        setError('Failed to connect to Intelligence API. Ensure backend is running.');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="dashboard-container" style={{ alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <div className="pulse" style={{ width: 48, height: 48, color: 'var(--accent-purple)' }}></div>
      </div>
    );
  }

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <div>
          <h1 className="dashboard-title">Retail Intelligence</h1>
          <p className="dashboard-subtitle">Purplle Tech Challenge \u2014 Live Analytics</p>
        </div>
        
        {error ? (
          <div className="status-badge error">
            <AlertCircle size={16} /> API Offline
          </div>
        ) : (
          <div className={`status-badge ${metrics?.data_confidence === 'LOW' ? 'error' : ''}`}>
            <div className="pulse"></div>
            {metrics?.data_confidence === 'LOW' ? 'Low Confidence Data' : 'Live Data Active'}
          </div>
        )}
      </header>

      {error && (
        <div className="anomaly-alert error glass-panel">
          <AlertCircle className="anomaly-icon" size={24} />
          <div>
            <h4>Connection Error</h4>
            <p className="anomaly-details">{error}</p>
          </div>
        </div>
      )}

      {anomalies && anomalies.anomaly_count > 0 && (
        <section className="anomalies-section">
          {anomalies.anomalies.map((anomaly, idx) => (
            <div key={idx} className={`anomaly-alert ${anomaly.severity}`}>
              <AlertTriangle className="anomaly-icon" size={24} />
              <div className="anomaly-content">
                <h4>{anomaly.type.replace(/_/g, ' ')}</h4>
                <p className="anomaly-details">{anomaly.details}</p>
                <div className="anomaly-action">Action: {anomaly.suggested_action}</div>
              </div>
            </div>
          ))}
        </section>
      )}

      {metrics && (
        <section className="metrics-grid">
          <div className="glass-panel metric-card">
            <div className="metric-header">
              <span>Unique Visitors</span>
              <Users className="metric-icon" size={20} />
            </div>
            <div className="metric-value">{metrics.unique_visitors}</div>
          </div>
          
          <div className="glass-panel metric-card">
            <div className="metric-header">
              <span>Conversion Rate</span>
              <ShoppingBag className="metric-icon" size={20} />
            </div>
            <div className="metric-value">{metrics.conversion_rate}%</div>
          </div>

          <div className="glass-panel metric-card">
            <div className="metric-header">
              <span>Queue Abandonment</span>
              <Activity className="metric-icon" size={20} />
            </div>
            <div className="metric-value">{metrics.queue_abandonment_rate_percent}%</div>
          </div>
        </section>
      )}

      <div className="main-grid">
        {funnel && (
          <section className="glass-panel">
            <h3 className="section-title">
              <Filter className="section-icon" size={20} />
              Conversion Funnel
            </h3>
            <div className="funnel-container">
              {funnel.stages.map((stage, idx) => (
                <div key={idx} className="funnel-stage">
                  <div 
                    className="funnel-bar-bg" 
                    style={{ width: `${stage.percentage}%` }}
                  ></div>
                  <div className="funnel-content">
                    <span className="funnel-label">{stage.stage}</span>
                    <div className="funnel-stats">
                      <span className="funnel-count">{stage.count}</span>
                      <span className="funnel-pct"> ({stage.percentage}%)</span>
                      {stage.drop_off_percent > 0 && (
                        <span className="dropoff-badge">-{stage.drop_off_percent}% drop</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {heatmap && (
          <section className="glass-panel">
            <h3 className="section-title">
              <Map className="section-icon" size={20} />
              Zone Heatmap
            </h3>
            <div className="heatmap-list">
              {heatmap.zones.map((zone, idx) => {
                // Color coding based on intensity
                let barColor = 'rgba(59, 130, 246, 0.8)';
                if (zone.normalised_score > 80) barColor = 'rgba(239, 68, 68, 0.8)';
                else if (zone.normalised_score > 50) barColor = 'rgba(245, 158, 11, 0.8)';

                return (
                  <div key={idx} className="heatmap-row">
                    <span className="heatmap-zone-name">{zone.zone_id}</span>
                    <div className="heatmap-bar-track">
                      <div 
                        className="heatmap-bar-fill" 
                        style={{ width: `${zone.normalised_score}%`, background: barColor }}
                      ></div>
                    </div>
                    <span className="heatmap-dwell">{zone.avg_dwell_seconds}s</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
