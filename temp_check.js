
    let mainChart = null;
    let currentTab = 'weight';
    let currentRangeMinutes = 1440; // Default 24 hours
    let timeOffsetMs = 0; // 0 = Live
    let rawEventsData = [];

    // Persistent set of dataset labels hidden by user
    let hiddenDatasets = new Set();
    try {
      const savedHidden = localStorage.getItem('cat_winsv_hidden_datasets');
      if (savedHidden) {
        hiddenDatasets = new Set(JSON.parse(savedHidden));
      }
    } catch (e) {
      console.error(e);
    }

    function saveHiddenDatasets() {
      try {
        localStorage.setItem('cat_winsv_hidden_datasets', JSON.stringify([...hiddenDatasets]));
      } catch (e) {
        console.error(e);
      }
    }

    function getDeviceFriendlyName(devId) {
      if (!devId) return '全体';
      if (devId.includes('bedroom')) return '寝室';
      if (devId.includes('living')) return 'リビング';
      if (devId.includes('feeder')) return 'ケージ';
      const found = rawEventsData.find(e => e.device_id === devId && e.note);
      if (found && found.note) return found.note;
      return devId;
    }

    Chart.defaults.color = '#94a3b8';
    Chart.defaults.borderColor = 'rgba(148, 163, 184, 0.08)';
    Chart.defaults.font.family = "'Outfit', 'Noto Sans JP', sans-serif";

    function initChart() {
      const ctx = document.getElementById('mainChart').getContext('2d');
      mainChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: [] },
        options: {
          animation: false,
          normalized: true,
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(15, 23, 42, 0.95)',
              titleColor: '#ffffff',
              bodyColor: '#f1f5f9',
              borderColor: 'rgba(56, 189, 248, 0.25)',
              borderWidth: 1,
              padding: 10,
              callbacks: {
                title: function(items) {
                  if (!items.length) return '';
                  const d = new Date(items[0].parsed.x);
                  return `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`;
                }
              }
            },
            zoom: {
              pan: {
                enabled: true,
                mode: 'x',
                onPan: function({ chart }) {
                  const xScale = chart.scales.x;
                  handlePanUpdate(xScale.min, xScale.max);
                }
              }
            }
          },
          scales: {
            x: {
              type: 'linear',
              grid: { color: 'rgba(148, 163, 184, 0.05)' }
            },
            y: {
              grid: { color: 'rgba(148, 163, 184, 0.05)' }
            }
          }
        }
      });
    }

    function handlePanUpdate(minTime, maxTime) {
      if (currentRangeMinutes === 0) return;
      const now = Date.now();
      timeOffsetMs = Math.max(0, now - maxTime);
      updateTimeNavUI(minTime, maxTime);
      updateYScaleForVisibleRange(minTime, maxTime);
    }

    function updateTimeNavUI(minTime, maxTime) {
      const liveIndicator = document.getElementById('live-indicator');
      const timeWindowText = document.getElementById('time-window-text');
      const btnNext = document.getElementById('btn-nav-next');

      const isLive = timeOffsetMs <= 60000;

      if (isLive) {
        liveIndicator.className = 'pulse-live';
        liveIndicator.textContent = '● LIVE';
        btnNext.disabled = true;
      } else {
        liveIndicator.className = 'pulse-past';
        liveIndicator.textContent = '⏱️ 過去';
        btnNext.disabled = false;
      }

      if (minTime && maxTime) {
        const dMin = new Date(minTime);
        const dMax = new Date(maxTime);
        const formatTime = (d) => `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
        timeWindowText.textContent = `${formatTime(dMin)} 〜 ${formatTime(dMax)}`;
      }
    }

    function panTimeStep(direction) {
      if (currentRangeMinutes === 0) return;
      const stepMs = (currentRangeMinutes * 60 * 1000) * 0.5;

      if (direction === -1) {
        timeOffsetMs += stepMs;
      } else {
        timeOffsetMs = Math.max(0, timeOffsetMs - stepMs);
      }

      renderChart();
    }

    function resetToLive() {
      timeOffsetMs = 0;
      renderChart();
    }

    function getXAxisConfig() {
      const now = Date.now();
      let min = null;
      let max = now - timeOffsetMs;
      let isShort = currentRangeMinutes <= 1440 && currentRangeMinutes > 0;

      if (currentRangeMinutes > 0) {
        min = max - (currentRangeMinutes * 60 * 1000);
      } else {
        max = null;
        isShort = false;
      }

      updateTimeNavUI(min, max);

      return {
        type: 'linear',
        min: min,
        max: max,
        grid: { color: 'rgba(148, 163, 184, 0.05)' },
        ticks: {
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 8,
          callback: function(val) {
            const d = new Date(val);
            if (isNaN(d.getTime())) return '';
            if (isShort) {
              return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
            } else {
              return `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:00`;
            }
          }
        }
      };
    }

    function updateYScaleForVisibleRange(minTime, maxTime) {
      if (!mainChart || !minTime || !maxTime) return;

      const filtered = rawEventsData.filter(e => {
        const t = new Date(e.timestamp).getTime();
        return t >= minTime && t <= maxTime;
      });

      if (currentTab === 'weight') {
        const weights = filtered.map(e => e.weight_g).filter(w => w !== null && w !== undefined && w >= 0 && w <= 1000);
        if (weights.length > 0) {
          const minV = Math.min(...weights);
          const maxV = Math.max(...weights);
          const latest = weights[0];

          const lower = Math.min(minV - 10, latest - 25);
          const upper = Math.max(maxV + 10, latest + 25);

          let yMin = Math.max(0, Math.floor(lower / 5) * 5);
          let yMax = Math.ceil(upper / 5) * 5;

          if (yMax - yMin < 30) {
            const center = Math.round(latest / 5) * 5;
            yMin = Math.max(0, center - 20);
            yMax = yMin + 40;
          }

          mainChart.options.scales.y.min = yMin;
          mainChart.options.scales.y.max = yMax;
          mainChart.update('none');
        }
      }
    }

    async function fetchData() {
      try {
        const fetchLimit = (currentRangeMinutes >= 10080 || currentRangeMinutes === 0) ? 40000 : 6000;
        const [sumRes, devRes, evRes] = await Promise.all([
          fetch('/api/v1/summary').then(r => r.json()),
          fetch('/api/v1/devices').then(r => r.json()),
          fetch(`/api/v1/events?limit=${fetchLimit}`).then(r => r.json())
        ]);

        updateSummary(sumRes);
        updateDevices(devRes.devices || []);
        rawEventsData = evRes.events || [];
        updateDeviceFilterDropdown();
        renderEventsTable();
        renderChart();
        document.getElementById('refresh-status').textContent = '● 自動更新中 (1分)';
      } catch (err) {
        console.error('Fetch error:', err);
        document.getElementById('refresh-status').textContent = '⚠️ 接続エラー';
      }
    }

    function updateSummary(s) {
      if (!s) return;

      if (s.latest_food_weight_g > 0 || (s.latest_food_time && s.latest_food_weight_g >= 0)) {
        document.getElementById('sum-food-weight').innerHTML = `${s.latest_food_weight_g.toFixed(1)} <span style="font-size: 0.95rem; font-weight: normal;">g</span>`;
        if (s.latest_food_time) {
          const dt = new Date(s.latest_food_time);
          document.getElementById('sum-food-time').textContent = `更新: ${dt.toLocaleTimeString()}`;
        }
      } else {
        document.getElementById('sum-food-weight').innerHTML = `-- <span style="font-size: 0.95rem; font-weight: normal;">g</span>`;
        document.getElementById('sum-food-time').textContent = `未測定`;
      }

      if (s.latest_cat_weight_g > 0) {
        document.getElementById('sum-cat-weight').innerHTML = `${s.latest_cat_weight_g.toFixed(1)} <span style="font-size: 0.95rem; font-weight: normal;">g</span> (${(s.latest_cat_weight_g / 1000).toFixed(2)} kg)`;
        const dt = new Date(s.latest_weight_time);
        document.getElementById('sum-cat-time').textContent = `測定: ${dt.toLocaleTimeString()}`;
      } else {
        document.getElementById('sum-cat-weight').innerHTML = `-- <span style="font-size: 0.95rem; font-weight: normal;">g</span>`;
        document.getElementById('sum-cat-time').textContent = `未測定`;
      }

      document.getElementById('sum-meals-count').innerHTML = `${s.today_meals_count} <span style="font-size: 0.95rem; font-weight: normal;">回</span>`;
      document.getElementById('sum-food-eaten').textContent = `食べた量: ${s.today_food_eaten_g.toFixed(1)}g`;

      // Multi-device environment support in summary card
      const envContainer = document.getElementById('sum-env-container');
      const envWrapper = document.getElementById('card-env-wrapper');

      if (s.latest_envs && s.latest_envs.length > 1) {
        envWrapper.classList.add('card-env-multi');
        envContainer.innerHTML = `
          <div class="env-chips-list">
            ${s.latest_envs.map(env => {
              const devName = env.note ? env.note : env.device_id;
              const tempStr = env.temperature_c !== null && env.temperature_c !== undefined ? `${env.temperature_c.toFixed(1)}°C` : '--.-°C';
              const humStr = env.humidity_pct !== null && env.humidity_pct !== undefined ? `${env.humidity_pct.toFixed(0)}%` : '--%';
              const pressStr = env.pressure_hpa !== null && env.pressure_hpa !== undefined ? `${env.pressure_hpa.toFixed(0)}hPa` : '--hPa';
              const co2Str = (env.co2_ppm !== null && env.co2_ppm !== undefined)
                ? `<span class="env-chip-co2" style="color: ${env.co2_ppm > 1500 ? '#f43f5e' : (env.co2_ppm > 1000 ? '#fb923c' : '#34d399')}; font-weight: 600;">🍃 ${env.co2_ppm.toFixed(0)}ppm</span>`
                : '';
              const dt = new Date(env.timestamp);
              return `
                <div class="env-chip-row">
                  <span class="env-chip-name">📍 ${escapeHtml(devName)}</span>
                  <div class="env-chip-data">
                    <span class="env-chip-temp">${tempStr}</span>
                    <span class="env-chip-hum">💧 ${humStr}</span>
                    ${co2Str}
                    <span class="env-chip-press">⏱️ ${pressStr}</span>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        `;
      } else if (s.latest_temp_c !== undefined && s.latest_temp_c !== null) {
        envWrapper.classList.remove('card-env-multi');
        const humStr = s.latest_humidity_pct !== undefined && s.latest_humidity_pct !== null ? `${s.latest_humidity_pct.toFixed(1)}%` : '--%';
        const pressStr = s.latest_pressure_hpa !== undefined && s.latest_pressure_hpa !== null ? `${s.latest_pressure_hpa.toFixed(0)} hPa` : '-- hPa';
        let devLabel = '';
        if (s.latest_envs && s.latest_envs.length === 1 && s.latest_envs[0].note) {
          devLabel = ` (${s.latest_envs[0].note})`;
        }
        envContainer.innerHTML = `
          <div class="card-value val-emerald">${s.latest_temp_c.toFixed(1)} <span style="font-size: 0.95rem; font-weight: normal;">°C</span></div>
          <div class="card-subtext">湿度: ${humStr} / 気圧: ${pressStr}${escapeHtml(devLabel)}</div>
        `;
      } else {
        envWrapper.classList.remove('card-env-multi');
        envContainer.innerHTML = `
          <div class="card-value val-emerald">--.- <span style="font-size: 0.95rem; font-weight: normal;">°C</span></div>
          <div class="card-subtext">湿度: --% / 気圧: -- hPa</div>
        `;
      }

      document.getElementById('sum-events-count').textContent = s.total_events_today;
      document.getElementById('sum-devices-count').innerHTML = `${s.active_devices_count} <span style="font-size: 0.95rem; font-weight: normal;">台</span>`;
    }

    function restoreStateFromUrlAndStorage() {
      const params = new URLSearchParams(window.location.search);
      const validRanges = [60, 180, 360, 1440, 10080, 0];
      const validTabs = ['weight', 'env', 'co2', 'pressure'];

      const urlRange = params.get('range');
      const savedRange = localStorage.getItem('cat_winsv_range');
      if (urlRange !== null && validRanges.includes(Number(urlRange))) {
        currentRangeMinutes = Number(urlRange);
      } else if (savedRange !== null && validRanges.includes(Number(savedRange))) {
        currentRangeMinutes = Number(savedRange);
      }

      const urlTab = params.get('tab');
      const savedTab = localStorage.getItem('cat_winsv_tab');
      if (urlTab && validTabs.includes(urlTab)) {
        currentTab = urlTab;
      } else if (savedTab && validTabs.includes(savedTab)) {
        currentTab = savedTab;
      }

      // Sync active UI buttons
      document.querySelectorAll('.range-btn').forEach(b => {
        const id = `range-${currentRangeMinutes}`;
        b.classList.toggle('active', b.id === id);
      });
      document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.toggle('active', b.id === `tab-${currentTab}`);
      });
    }

    function syncStateToUrlAndStorage() {
      localStorage.setItem('cat_winsv_range', currentRangeMinutes);
      localStorage.setItem('cat_winsv_tab', currentTab);
      const newUrl = `${window.location.pathname}?range=${currentRangeMinutes}&tab=${currentTab}`;
      window.history.replaceState(null, '', newUrl);
    }

    function switchGraphTab(tab) {
      currentTab = tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      const activeBtn = document.getElementById(`tab-${tab}`);
      if (activeBtn) activeBtn.classList.add('active');
      syncStateToUrlAndStorage();
      renderChart();
    }

    async function setGraphRange(minutes) {
      currentRangeMinutes = minutes;
      timeOffsetMs = 0;
      document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
      const id = `range-${minutes}`;
      const btn = document.getElementById(id);
      if (btn) btn.classList.add('active');
      syncStateToUrlAndStorage();

      document.getElementById('refresh-status').textContent = '読み込み中...';
      await fetchData();
    }

    function renderChart() {
      if (!mainChart || rawEventsData.length === 0) return;

      const xAxisConfig = getXAxisConfig();
      const minTime = xAxisConfig.min;
      const maxTime = xAxisConfig.max;

      const visibleEvents = minTime && maxTime
        ? rawEventsData.filter(e => {
            const t = new Date(e.timestamp).getTime();
            return t >= minTime && t <= maxTime;
          })
        : rawEventsData;

      const filtered = [...rawEventsData].reverse();

      if (currentTab === 'weight') {
        const weightData = filtered
          .map(e => ({ x: new Date(e.timestamp).getTime(), y: e.weight_g }))
          .filter(pt => pt.y !== null && pt.y !== undefined && pt.y >= 0 && pt.y <= 1000);

        const visibleWeights = visibleEvents.map(e => e.weight_g).filter(w => w !== null && w !== undefined && w >= 0 && w <= 1000);

        let yMin = 200, yMax = 260;
        if (visibleWeights.length > 0) {
          const minV = Math.min(...visibleWeights);
          const maxV = Math.max(...visibleWeights);
          const latest = visibleWeights[0];

          const lower = Math.min(minV - 10, latest - 25);
          const upper = Math.max(maxV + 10, latest + 25);

          yMin = Math.max(0, Math.floor(lower / 5) * 5);
          yMax = Math.ceil(upper / 5) * 5;

          if (yMax - yMin < 30) {
            const center = Math.round(latest / 5) * 5;
            yMin = Math.max(0, center - 20);
            yMax = yMin + 40;
          }
        }

        mainChart.data = {
          datasets: [{
            label: '餌皿残量 (g)',
            data: weightData,
            borderColor: '#fb923c',
            backgroundColor: 'rgba(251, 146, 60, 0.15)',
            fill: true,
            tension: 0.3,
            pointRadius: 3,
            pointBackgroundColor: '#fb923c',
            borderWidth: 2
          }]
        };
        mainChart.options.scales = {
          x: xAxisConfig,
          y: {
            title: { display: true, text: '重量 (g)', color: '#fb923c' },
            grid: { color: 'rgba(148, 163, 184, 0.05)' },
            min: yMin,
            max: yMax
          }
        };

      } else if (currentTab === 'env') {
        const envDevices = [...new Set(filtered.filter(e => e.temperature_c !== null && e.temperature_c !== undefined).map(e => e.device_id || 'default'))];
        const tempDatasets = [];
        const humDatasets = [];
        const colors = [
          { temp: '#34d399', hum: '#38bdf8' }, // Emerald / Sky
          { temp: '#fb923c', hum: '#a78bfa' }, // Orange / Violet
          { temp: '#f43f5e', hum: '#22d3ee' }, // Rose / Cyan
          { temp: '#eab308', hum: '#818cf8' }  // Yellow / Indigo
        ];

        // 1. Add all Temperature datasets first
        envDevices.forEach((devId, idx) => {
          const c = colors[idx % colors.length];
          const devLabel = envDevices.length > 1 ? `[${devId}] ` : '';
          const devEvents = filtered.filter(e => (e.device_id || 'default') === devId);
          const tData = devEvents.map(e => ({ x: new Date(e.timestamp).getTime(), y: e.temperature_c })).filter(pt => pt.y !== null && pt.y !== undefined && pt.y >= -20 && pt.y <= 60);

          if (tData.length > 0) {
            tempDatasets.push({
              label: `${devLabel}室温 (°C)`,
              data: tData,
              borderColor: c.temp,
              backgroundColor: c.temp + '1a',
              yAxisID: 'yTemp',
              tension: 0.3,
              borderWidth: 2,
              pointRadius: 2
            });
          }
        });

        // 2. Add all Humidity datasets next
        envDevices.forEach((devId, idx) => {
          const c = colors[idx % colors.length];
          const devLabel = envDevices.length > 1 ? `[${devId}] ` : '';
          const devEvents = filtered.filter(e => (e.device_id || 'default') === devId);
          const hData = devEvents.map(e => ({ x: new Date(e.timestamp).getTime(), y: e.humidity_pct })).filter(pt => pt.y !== null && pt.y !== undefined && pt.y >= 0 && pt.y <= 100);

          if (hData.length > 0) {
            humDatasets.push({
              label: `${devLabel}湿度 (%)`,
              data: hData,
              borderColor: c.hum,
              backgroundColor: c.hum + '1a',
              borderDash: [4, 4],
              yAxisID: 'yHum',
              tension: 0.3,
              borderWidth: 2,
              pointRadius: 2
            });
          }
        });

        mainChart.data = { datasets: [...tempDatasets, ...humDatasets] };
        mainChart.options.scales = {
          x: xAxisConfig,
          yTemp: {
            type: 'linear',
            position: 'left',
            title: { display: true, text: '温度 (°C)', color: '#34d399' },
            grid: { color: 'rgba(148, 163, 184, 0.05)' }
          },
          yHum: {
            type: 'linear',
            position: 'right',
            title: { display: true, text: '湿度 (%)', color: '#38bdf8' },
            grid: { drawOnChartArea: false },
            suggestedMin: 0,
            suggestedMax: 100
          }
        };

      } else if (currentTab === 'co2') {
        const co2Devices = [...new Set(filtered.filter(e => e.co2_ppm !== null && e.co2_ppm !== undefined && Number(e.co2_ppm) > 0).map(e => e.device_id || 'default'))];
        const colors = ['#34d399', '#38bdf8', '#fb923c', '#a78bfa'];
        const datasets = [];

        co2Devices.forEach((devId, idx) => {
          const c = colors[idx % colors.length];
          const devLabel = co2Devices.length > 1 ? `[${devId}] ` : '';
          const devEvents = filtered.filter(e => (e.device_id || 'default') === devId);
          const cData = devEvents
            .filter(e => e.co2_ppm !== null && e.co2_ppm !== undefined)
            .map(e => ({ x: new Date(e.timestamp).getTime(), y: Number(e.co2_ppm) }))
            .filter(pt => !isNaN(pt.y) && pt.y >= 350 && pt.y <= 10000);

          if (cData.length > 0) {
            datasets.push({
              label: `${devLabel}CO2 (ppm)`,
              data: cData,
              borderColor: c,
              backgroundColor: c + '1a',
              tension: 0.3,
              borderWidth: 2,
              pointRadius: 2
            });
          }
        });

        // Calculate dynamic Y-axis max for CO2 (lower bound fixed at 400ppm)
        const visibleCo2Values = visibleEvents
          .map(e => (e.co2_ppm !== null && e.co2_ppm !== undefined) ? Number(e.co2_ppm) : null)
          .filter(v => v !== null && !isNaN(v) && v >= 350 && v <= 10000);

        let yMax = 1000;
        if (visibleCo2Values.length > 0) {
          const maxV = Math.max(...visibleCo2Values);
          // Margin +60ppm and round up to clean 50ppm boundary
          yMax = Math.max(800, Math.ceil((maxV + 60) / 50) * 50);
        }

        mainChart.data = { datasets };
        mainChart.options.scales = {
          x: xAxisConfig,
          y: {
            min: 400, // センサー最低値 (下限 400ppm 固定)
            max: yMax, // 表示範囲内の最大値に合わせて上限を自動可変
            title: { display: true, text: 'CO2濃度 (ppm)', color: '#34d399' },
            grid: { color: 'rgba(148, 163, 184, 0.05)' }
          }
        };

      } else if (currentTab === 'pressure') {
        const pressDevices = [...new Set(filtered.filter(e => e.pressure_hpa !== null && e.pressure_hpa !== undefined).map(e => e.device_id || 'default'))];
        const devStyles = [
          { color: '#a78bfa', dash: [], point: 'circle' },        // 寝室 (Violet 実線)
          { color: '#34d399', dash: [4, 4], point: 'rectRot' },   // リビング (Emerald 破線)
          { color: '#fb923c', dash: [2, 2], point: 'triangle' },  // ケージ (Orange 点線)
          { color: '#38bdf8', dash: [6, 3], point: 'cross' }      // その他 (Sky 一点鎖線)
        ];
        const datasets = [];

        pressDevices.forEach((devId, idx) => {
          const style = devStyles[idx % devStyles.length];
          const friendlyName = getDeviceFriendlyName(devId);
          const devLabel = `[${friendlyName}] `;
          const devEvents = filtered.filter(e => (e.device_id || 'default') === devId);
          const pData = devEvents.map(e => ({ x: new Date(e.timestamp).getTime(), y: Number(e.pressure_hpa) })).filter(pt => !isNaN(pt.y) && pt.y >= 800 && pt.y <= 1200);

          if (pData.length > 0) {
            datasets.push({
              label: `${devLabel}気圧 (hPa)`,
              data: pData,
              borderColor: style.color,
              backgroundColor: style.color + '1a',
              borderDash: style.dash,
              pointStyle: style.point,
              tension: 0.3,
              borderWidth: 2,
              pointRadius: 3
            });
          }
        });

        // Calculate dynamic Y-axis for Pressure (tight zoom for subtle variations)
        const visiblePressValues = visibleEvents
          .map(e => (e.pressure_hpa !== null && e.pressure_hpa !== undefined) ? Number(e.pressure_hpa) : null)
          .filter(v => v !== null && !isNaN(v) && v >= 800 && v <= 1200);

        let pMin = 990, pMax = 1030;
        if (visiblePressValues.length > 0) {
          const minV = Math.min(...visiblePressValues);
          const maxV = Math.max(...visiblePressValues);
          const center = (minV + maxV) / 2;
          const span = Math.max(4, (maxV - minV) * 1.6); // Minimum 4hPa span
          pMin = Math.floor(center - span / 2);
          pMax = Math.ceil(center + span / 2);
        }

        mainChart.data = { datasets };
        mainChart.options.scales = {
          x: xAxisConfig,
          y: {
            min: pMin,
            max: pMax,
            title: { display: true, text: '気圧 (hPa)', color: '#a78bfa' },
            grid: { color: 'rgba(148, 163, 184, 0.05)' }
          }
        };
      }

      // Restore persisted hidden states for datasets
      if (mainChart.data && mainChart.data.datasets) {
        mainChart.data.datasets.forEach((ds, idx) => {
          if (hiddenDatasets.has(ds.label)) {
            mainChart.setDatasetVisibility(idx, false);
          } else {
            mainChart.setDatasetVisibility(idx, true);
          }
        });
      }

      mainChart.update('none');
      updateCustomLegend();
    }

    function updateCustomLegend() {
      const container = document.getElementById('chart-custom-legend');
      if (!container || !mainChart) return;

      const datasets = mainChart.data.datasets || [];
      if (datasets.length === 0) {
        container.style.display = 'none';
        return;
      }
      container.style.display = 'flex';

      if (currentTab === 'env') {
        const tempItems = [];
        const humItems = [];

        datasets.forEach((ds, idx) => {
          const isVisible = mainChart.isDatasetVisible(idx);
          const isHum = (ds.yAxisID === 'yHum');
          const isHiddenClass = isVisible ? '' : 'hidden';
          const itemHtml = `
            <div class="legend-item ${isHiddenClass}" onclick="toggleDataset(${idx})" title="クリックで線の表示/非表示を切り替え">
              <span class="legend-color-box" style="background-color: ${ds.borderColor};"></span>
              <span>${escapeHtml(ds.label)}</span>
            </div>
          `;
          if (isHum) {
            humItems.push(itemHtml);
          } else {
            tempItems.push(itemHtml);
          }
        });

        container.innerHTML = `
          <div class="legend-group-row">
            <span class="legend-group-title">🌡️ 温度:</span>
            ${tempItems.join('')}
          </div>
          <div class="legend-group-row">
            <span class="legend-group-title">💧 湿度:</span>
            ${humItems.join('')}
          </div>
        `;
      } else {
        const items = datasets.map((ds, idx) => {
          const isVisible = mainChart.isDatasetVisible(idx);
          const isHiddenClass = isVisible ? '' : 'hidden';
          return `
            <div class="legend-item ${isHiddenClass}" onclick="toggleDataset(${idx})" title="クリックで線の表示/非表示を切り替え">
              <span class="legend-color-box" style="background-color: ${ds.borderColor};"></span>
              <span>${escapeHtml(ds.label)}</span>
            </div>
          `;
        });
        container.innerHTML = `
          <div class="legend-group-row">
            ${items.join('')}
          </div>
        `;
      }
    }

    function toggleDataset(index) {
      if (!mainChart) return;
      const ds = mainChart.data.datasets[index];
      if (!ds) return;

      const isVisible = mainChart.isDatasetVisible(index);
      const nextVisible = !isVisible;
      mainChart.setDatasetVisibility(index, nextVisible);

      if (!nextVisible) {
        hiddenDatasets.add(ds.label);
      } else {
        hiddenDatasets.delete(ds.label);
      }
      saveHiddenDatasets();

      mainChart.update();
      updateCustomLegend();
    }

    let displayedCount = 50;
    const PAGE_CHUNK_SIZE = 50;
    let currentDisplayMode = 'auto'; // 'auto', '100', '300', '500', 'all'
    let tableFilterKeyword = '';
    let tableFilterDevice = 'all';
    let tableFilterEventType = 'all';

    function handleDisplayCountChange(val) {
      currentDisplayMode = val;
      if (val === 'all') {
        displayedCount = rawEventsData.length;
      } else if (val === 'auto') {
        displayedCount = 50;
      } else {
        displayedCount = parseInt(val, 10);
      }
      renderEventsTable();
    }

    function handleFilterChange() {
      const kwInput = document.getElementById('filter-keyword');
      const devSelect = document.getElementById('filter-device');
      const typeSelect = document.getElementById('filter-event-type');

      if (kwInput) tableFilterKeyword = kwInput.value;
      if (devSelect) tableFilterDevice = devSelect.value;
      if (typeSelect) tableFilterEventType = typeSelect.value;

      displayedCount = 50; // reset pagination on filter change
      renderEventsTable();
    }

    function resetTableFilters() {
      tableFilterKeyword = '';
      tableFilterDevice = 'all';
      tableFilterEventType = 'all';

      const kwInput = document.getElementById('filter-keyword');
      const devSelect = document.getElementById('filter-device');
      const typeSelect = document.getElementById('filter-event-type');

      if (kwInput) kwInput.value = '';
      if (devSelect) devSelect.value = 'all';
      if (typeSelect) typeSelect.value = 'all';

      displayedCount = 50;
      renderEventsTable();
    }

    function updateDeviceFilterDropdown() {
      const devSelect = document.getElementById('filter-device');
      if (!devSelect || !rawEventsData) return;

      const currentVal = devSelect.value || 'all';
      const deviceMap = new Map();

      rawEventsData.forEach(e => {
        if (e.device_id && !deviceMap.has(e.device_id)) {
          deviceMap.set(e.device_id, e.note || e.device_id);
        }
      });

      let optionsHtml = '<option value="all">すべてのデバイス</option>';
      deviceMap.forEach((note, devId) => {
        const label = (note && note !== devId) ? `${devId} (${note})` : devId;
        const selected = (currentVal === devId) ? 'selected' : '';
        optionsHtml += `<option value="${escapeHtml(devId)}" ${selected}>${escapeHtml(label)}</option>`;
      });

      devSelect.innerHTML = optionsHtml;
    }

    function getFilteredTableEvents() {
      return rawEventsData.filter(e => {
        // 1. Device filter
        if (tableFilterDevice !== 'all' && (e.device_id || 'default') !== tableFilterDevice) {
          return false;
        }
        // 2. Event type filter
        if (tableFilterEventType !== 'all' && e.event_type !== tableFilterEventType) {
          return false;
        }
        // 3. Keyword filter (searches note, device_id, and event_type)
        if (tableFilterKeyword && tableFilterKeyword.trim()) {
          const q = tableFilterKeyword.trim().toLowerCase();
          const noteStr = (e.note || '').toLowerCase();
          const devStr = (e.device_id || '').toLowerCase();
          const typeStr = (e.event_type || '').toLowerCase();
          if (!noteStr.includes(q) && !devStr.includes(q) && !typeStr.includes(q)) {
            return false;
          }
        }
        return true;
      });
    }

    function createTableRowHtml(e) {
      const dt = new Date(e.timestamp);
      const timeStr = `${dt.toLocaleDateString()} ${dt.toLocaleTimeString()}`;

      let eventLabel = escapeHtml(e.event_type);
      let eventBadgeClass = 'badge-sensor';
      if (e.event_type === 'meal_finished') {
        eventLabel = '🥣 食事完了';
        eventBadgeClass = 'badge-feeder';
      } else if (e.event_type === 'refill') {
        eventLabel = '✨ フード補充';
        eventBadgeClass = 'badge-scale';
      } else if (e.event_type === 'food_level') {
        eventLabel = '🍽️ 定期残量';
        eventBadgeClass = 'badge-sensor';
      } else if (e.event_type === 'weight_measured') {
        eventLabel = '⚖️ 体重測定';
        eventBadgeClass = 'badge-scale';
      }

      let weightStr = `${e.weight_g !== undefined && e.weight_g !== null ? e.weight_g.toFixed(1) + 'g' : '-'}`;
      if (e.delta_g !== undefined && e.delta_g !== null) {
        const deltaVal = Number(e.delta_g);
        if (deltaVal < 0) {
          weightStr += ` <span style="color: var(--accent-orange); font-weight: 700;">(${deltaVal.toFixed(1)}g)</span>`;
        } else if (deltaVal > 0) {
          weightStr += ` <span style="color: var(--accent-emerald); font-weight: 700;">(+${deltaVal.toFixed(1)}g)</span>`;
        }
      }

      let envStr = '-';
      if (e.temperature_c !== undefined && e.temperature_c !== null) {
        const tStr = `${e.temperature_c.toFixed(1)}°C`;
        const hStr = e.humidity_pct ? `${e.humidity_pct.toFixed(0)}%` : '';
        const cStr = (e.co2_ppm !== undefined && e.co2_ppm !== null) ? ` / 🍃 ${Number(e.co2_ppm).toFixed(0)}ppm` : '';
        envStr = `${tStr} / ${hStr}${cStr}`;
      }

      return `
        <tr>
          <td style="font-family: 'JetBrains Mono', monospace; font-size: 0.78rem;">${timeStr}</td>
          <td><strong>${escapeHtml(e.device_id)}</strong></td>
          <td><span class="badge badge-${e.device_type || 'sensor'}">${escapeHtml(e.device_type)}</span></td>
          <td><span class="badge ${eventBadgeClass}">${eventLabel}</span></td>
          <td style="text-align: right; font-family: 'JetBrains Mono', monospace; font-weight: 600;">${weightStr}</td>
          <td style="font-size: 0.78rem; color: var(--text-muted);">${envStr}</td>
          <td style="color: var(--text-muted); font-size: 0.78rem;">${escapeHtml(e.note || '')}</td>
        </tr>
      `;
    }

    function renderEventsTable() {
      const tbody = document.getElementById('events-tbody');
      const badge = document.getElementById('table-count-badge');
      const footerText = document.getElementById('table-footer-text');
      
      const filteredEvents = getFilteredTableEvents();
      const total = filteredEvents.length;
      const allTotal = rawEventsData.length;

      if (!rawEventsData || allTotal === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">データを受信していません。</td></tr>`;
        if (badge) badge.textContent = '0 件';
        if (footerText) footerText.textContent = 'データなし';
        return;
      }

      if (total === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">🔍 条件に一致するログが見つかりませんでした。</td></tr>`;
        if (badge) badge.textContent = `0 / ${allTotal} 件`;
        if (footerText) footerText.textContent = '該当ログなし';
        return;
      }

      const limit = (currentDisplayMode === 'all') ? total : Math.min(displayedCount, total);
      const isFiltered = (total !== allTotal);
      if (badge) badge.textContent = isFiltered ? `${limit} / ${total} 件 (絞り込み中)` : `${limit} / ${total} 件`;

      const visibleEvents = filteredEvents.slice(0, limit);
      tbody.innerHTML = visibleEvents.map(e => createTableRowHtml(e)).join('');

      if (footerText) {
        if (limit >= total) {
          footerText.innerHTML = `<span style="color: var(--text-dim); font-size: 0.76rem;">✅ 全 ${total} 件のログを表示中</span>`;
        } else {
          const nextCount = Math.min(PAGE_CHUNK_SIZE, total - limit);
          footerText.innerHTML = `
            <button class="load-more-btn" onclick="loadMoreEvents()">
              ⬇️ さらに過去のログを読み込む (+${nextCount}件)
            </button>
          `;
        }
      }
    }

    function loadMoreEvents() {
      if (displayedCount < rawEventsData.length) {
        displayedCount += PAGE_CHUNK_SIZE;
        renderEventsTable();
      }
    }

    function setupTableInfiniteScroll() {
      const container = document.getElementById('events-table-container');
      if (!container) return;

      container.addEventListener('scroll', () => {
        if (currentDisplayMode !== 'auto') return;
        // Trigger auto load when scrolled near bottom (within 80px)
        if (container.scrollTop + container.clientHeight >= container.scrollHeight - 80) {
          if (displayedCount < rawEventsData.length) {
            displayedCount += PAGE_CHUNK_SIZE;
            renderEventsTable();
          }
        }
      });
    }

    function updateDevices(devices) {
      const container = document.getElementById('devices-list');
      if (devices.length === 0) {
        container.innerHTML = `<div class="empty-state" style="background: var(--bg-card); border-radius: 12px; border: 1px solid var(--border-slate);">デバイス未登録</div>`;
        return;
      }

      container.innerHTML = devices.map(d => {
        const isOnline = d.is_online;
        const lastSeen = new Date(d.last_seen).toLocaleTimeString();
        let valueStr = `${d.last_weight_g.toFixed(1)}g`;
        if (d.last_temp_c !== undefined && d.last_temp_c !== null) {
          valueStr = `${d.last_temp_c.toFixed(1)}°C / ${d.last_humidity ? d.last_humidity.toFixed(1) + '%' : ''}`;
        }
        return `
          <div class="device-item">
            <div class="device-header">
              <div class="device-id">
                <span class="status-dot ${isOnline ? 'status-online' : 'status-offline'}"></span>
                ${escapeHtml(d.device_id)}
              </div>
              <span class="badge badge-${d.device_type || 'sensor'}">${escapeHtml(d.device_type)}</span>
            </div>
            <div class="device-meta">
              <span>最終値: <strong>${valueStr}</strong></span>
              <span>${lastSeen}</span>
            </div>
          </div>
        `;
      }).join('');
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    restoreStateFromUrlAndStorage();
    initChart();
    setupTableInfiniteScroll();
    fetchData();
    setInterval(fetchData, 60000); // 1分おきに自動更新
  