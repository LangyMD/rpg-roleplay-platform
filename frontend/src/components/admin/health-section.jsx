/* Admin — AdminHealthPage — 系统健康。从 pages/admin.jsx 纯机械拆出,JSX / props / fetch 路径零变化。 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSButton from '@cloudscape-design/components/button';
import CSBox from '@cloudscape-design/components/box';
import CSAlert from '@cloudscape-design/components/alert';
import CSColumnLayout from '@cloudscape-design/components/column-layout';
import CSStatusIndicator from '@cloudscape-design/components/status-indicator';
import { uiLocale } from '../../i18n/index.js';

/* ─────────────────────────────────────────────────────────────────
   页面 4：AdminHealthPage — 系统健康
   ───────────────────────────────────────────────────────────────── */
export function AdminHealthPage() {
  const { t } = useTranslation();
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [err, setErr] = React.useState(null);
  const [lastUpdate, setLastUpdate] = React.useState(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const fetchHealth = React.useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    else setLoading(true);
    setErr(null);
    try {
      const res = await window.api.admin.health();
      setData(res);
      setLastUpdate(new Date());
    } catch (e) {
      setErr(e?.message || t('admin_page.common.load_fail'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    fetchHealth();
    const id = setInterval(() => {
      if (!cancelled) fetchHealth();
    }, 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [fetchHealth]);

  const db = data?.database || data?.db || {};
  const mem = data?.memory || {};
  const disk = data?.disk || {};
  const proc = data?.process || data?.proc || {};
  const diskPct = typeof disk.used_percent === 'number' ? disk.used_percent : null;

  return (
    <CSSpaceBetween size="l">
      {err && <CSAlert type="error" header={t('admin_page.common.load_fail')}>{err}</CSAlert>}
      <CSContainer
        header={
          <CSHeader
            variant="h2"
            description={t('admin_page.health.description')}
            actions={
              <CSSpaceBetween direction="horizontal" size="xs">
                {lastUpdate && (
                  <CSBox color="text-body-secondary" variant="small">
                    {t('admin_page.health.last_update', { time: lastUpdate.toLocaleTimeString(uiLocale(), { hour12: false }) })}
                  </CSBox>
                )}
                <CSButton iconName="refresh" loading={refreshing} onClick={() => fetchHealth(true)}>{t('admin_page.common.refresh')}</CSButton>
              </CSSpaceBetween>
            }
          >
            {t('admin_page.health.title')}
          </CSHeader>
        }
      >
        {loading && !data
          ? <CSBox color="inherit">{t('admin_page.common.loading')}</CSBox>
          : !data
            ? <CSBox textAlign="center" color="inherit">{t('admin_page.health.empty')}</CSBox>
            : (
              <CSColumnLayout columns={2} variant="text-grid">
                <div>
                  <CSSpaceBetween size="s">
                    <div>
                      <strong>{t('admin_page.health.db_title')}</strong>
                      <div>
                        <CSStatusIndicator type={db.ok === false ? 'error' : 'success'}>
                          {db.ok === false ? t('admin_page.health.db_fail') : t('admin_page.health.db_ok')}
                        </CSStatusIndicator>
                        {typeof db.latency_ms === 'number' && (
                          <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--color-text-body-secondary)' }}>
                            {t('admin_page.health.db_latency', { ms: db.latency_ms })}
                          </span>
                        )}
                      </div>
                    </div>
                    <div>
                      <strong>{t('admin_page.health.mem_title')}</strong>
                      <div>
                        {typeof mem.rss_mb === 'number'
                          ? <CSStatusIndicator type="success">RSS {mem.rss_mb} MB</CSStatusIndicator>
                          : <CSStatusIndicator type="pending">{t('admin_page.health.mem_no_data')}</CSStatusIndicator>
                        }
                      </div>
                    </div>
                  </CSSpaceBetween>
                </div>
                <div>
                  <CSSpaceBetween size="s">
                    <div>
                      <strong>{t('admin_page.health.disk_title')}</strong>
                      <div>
                        {diskPct !== null
                          ? <CSStatusIndicator type={diskPct > 90 ? 'warning' : 'success'}>
                              {t('admin_page.health.disk_used', { pct: diskPct })}
                            </CSStatusIndicator>
                          : <CSStatusIndicator type="pending">{t('admin_page.health.disk_no_data')}</CSStatusIndicator>
                        }
                      </div>
                    </div>
                    <div>
                      <strong>{t('admin_page.health.proc_title')}</strong>
                      <div>
                        {proc.pid
                          ? <CSStatusIndicator type="success">
                              PID {proc.pid}
                              {proc.uptime_s && <span style={{ marginLeft: 8, fontSize: 12 }}>{t('admin_page.health.proc_uptime', { min: Math.round(proc.uptime_s / 60) })}</span>}
                            </CSStatusIndicator>
                          : <CSStatusIndicator type="pending">{t('admin_page.health.proc_no_data')}</CSStatusIndicator>
                        }
                      </div>
                    </div>
                  </CSSpaceBetween>
                </div>
              </CSColumnLayout>
            )
        }
      </CSContainer>
    </CSSpaceBetween>
  );
}
