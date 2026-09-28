// Interview Coach: Chart.js 4 theme (app/static/chart-theme.js), loaded after chart-4.4.7.umd.js. It reads the CSS variables, so dark mode works automatically.
(function () {
  if (!window.Chart) return;
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const C = window.Chart;
  C.defaults.font.family = css('--font-body') || 'system-ui, sans-serif';
  C.defaults.font.size = 13;
  C.defaults.font.weight = 600;
  C.defaults.color = css('--muted');
  C.defaults.borderColor = css('--line-soft');
  C.defaults.animation.duration = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 500;
  C.defaults.plugins.legend.display = false;
  Object.assign(C.defaults.plugins.tooltip, {
    backgroundColor: css('--fg'), titleColor: css('--bg'), bodyColor: css('--bg'),
    padding: 10, cornerRadius: 12, displayColors: false,
    titleFont: { weight: 700 }, bodyFont: { weight: 500 },
  });
  C.defaults.elements.bar.borderRadius = 12;
  C.defaults.elements.bar.borderSkipped = false;
  C.defaults.elements.line.borderWidth = 3;
  C.defaults.elements.line.tension = 0.35;
  C.defaults.elements.point.radius = 4;
  C.defaults.elements.point.hoverRadius = 6;
  C.defaults.scale.grid.display = false;
  C.defaults.scale.border.display = false;

  window.icTheme = {
    ok: css('--sage-500'), weak: css('--accent'), neutral: css('--line'),
    sage: css('--sage-600'), accent: css('--accent-strong'),
    // STAR: horizontal bars. The weakest part is terracotta, the rest sage.
    star(d) {
      const vals = Object.values(d).map(v => Math.round(v * 100));
      const min = Math.min(...vals);
      return {
        type: 'bar',
        data: { labels: Object.keys(d), datasets: [{ label: '%', data: vals, backgroundColor: vals.map(v => v === min ? this.weak : this.ok), barThickness: 16 }] },
        options: { indexAxis: 'y', scales: { x: { min: 0, max: 100, grid: { display: true, color: css('--line-soft') }, ticks: { callback: v => v + '%' } }, y: { ticks: { color: css('--fg') } } } },
      };
    },
    // Quality 0–3: bars coloured low → high (terracotta-300, neutral, sage).
    quality(d, label) {
      const cols = [css('--line'), css('--accent-300'), css('--line'), this.ok];
      return { type: 'bar', data: { labels: Object.keys(d).map(k => label + ' ' + k), datasets: [{ data: Object.values(d), backgroundColor: cols, borderRadius: { topLeft: 14, topRight: 14, bottomLeft: 4, bottomRight: 4 }, maxBarThickness: 64 }] },
        options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { display: true, color: css('--line-soft') } } } } };
    },
    // Speaking: wpm (sage, solid) + fillers/min (terracotta, dashed). Two axes.
    speaking(rows) {
      return { type: 'line', data: { labels: rows.map(x => '#' + x.n), datasets: [
        { label: 'wpm', data: rows.map(x => x.wpm), borderColor: this.sage, backgroundColor: this.sage, yAxisID: 'y' },
        { label: 'fillers/min', data: rows.map(x => x.fillers), borderColor: this.accent, backgroundColor: this.accent, borderDash: [6, 5], yAxisID: 'y1' } ] },
        options: { plugins: { legend: { display: true, position: 'bottom', labels: { usePointStyle: true, boxWidth: 8 } } },
          scales: { y: { grid: { display: true, color: css('--line-soft') } }, y1: { position: 'right' } } } };
    },
  };
})();

// In review.html:
//   new Chart(starChart, icTheme.star(d.star));
//   new Chart(qualityChart, icTheme.quality(d.quality, "{{ t('review.level') }}"));
//   if (s) new Chart(s, icTheme.speaking(d.speaking));
