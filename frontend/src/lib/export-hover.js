// Hover read-outs in exported reports, as the viewer has them: the values under the cursor on
// line charts (click pins them), the nearest threshold on PR curves and the bin on distributions.
// Plain browser JavaScript, inlined into the exported HTML file.
(function () {
  var count = function (v) {
    return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(1);
  };
  var num = function (v) {
    var a = Math.abs(v);
    return a !== 0 && (a >= 1e5 || a < 1e-3) ? v.toExponential(3) : String(+v.toPrecision(5));
  };
  var line = function (tip, text, color, cls) {
    var row = document.createElement('span');
    if (cls) row.className = cls;
    if (color) {
      var sw = document.createElement('i');
      sw.style.background = color;
      row.appendChild(sw);
    }
    row.appendChild(document.createTextNode(text));
    tip.appendChild(row);
  };
  var make = function (box, cls) {
    var el = document.createElement(cls === 'nbdot' ? 'span' : 'div');
    el.className = cls;
    el.hidden = true;
    box.appendChild(el);
    return el;
  };
  // put the read-out beside (px, py) in the box, on the side with more room
  var place = function (tip, box, px, py) {
    var w = box.clientWidth;
    tip.style.top = py + 'px';
    if (px > w / 2) {
      tip.style.left = '';
      tip.style.right = w - px + 12 + 'px';
    } else {
      tip.style.right = '';
      tip.style.left = px + 12 + 'px';
    }
  };

  // SVG snapshots (the Timeline): a title with several lines becomes a hover card, as in the viewer
  document.querySelectorAll('.nbsvg').forEach(function (box) {
    box.querySelectorAll('title').forEach(function (t) {
      var lines = (t.textContent || '').split(/\n|\\n/).filter(function (l) {
        return l.trim();
      });
      if (lines.length < 2 || !t.parentNode) return;
      t.parentNode.setAttribute('data-card', JSON.stringify(lines));
      t.parentNode.removeChild(t);
    });
    box.style.position = 'relative';
    var tip = make(box, 'nbtip nbcard');
    box.addEventListener('pointerleave', function () {
      tip.hidden = true;
    });
    box.addEventListener('pointermove', function (e) {
      var el = e.target.closest ? e.target.closest('[data-card]') : null;
      if (!el) {
        tip.hidden = true;
        return;
      }
      tip.textContent = '';
      JSON.parse(el.getAttribute('data-card')).forEach(function (text, i) {
        var cls = i === 0 ? 'nbtip-head' : i === 1 ? 'nbtip-faint' : text.charAt(0) === '\u26a0' ? 'nbtip-warn' : '';
        line(tip, text, null, cls);
      });
      tip.hidden = false;
      var r = box.getBoundingClientRect();
      var y = e.clientY - r.top;
      place(tip, box, e.clientX - r.left + box.scrollLeft, y < r.height * 0.6 ? y + 14 : y - 14);
      tip.style.transform = y < r.height * 0.6 ? 'none' : 'translateY(-100%)';
    });
  });

  // PR curves and distributions: an SVG plus its series as JSON
  document.querySelectorAll('.nbpr').forEach(function (box) {
    var json = box.querySelector('script.nbhov');
    var svg = box.querySelector('svg');
    if (!json || !svg) return;
    var d = JSON.parse(json.textContent);
    var b = d.box;
    var iw = d.w - b.left - b.right;
    var ih = d.h - b.top - b.bottom;
    box.style.position = 'relative';
    var tip = make(box, 'nbtip');
    var dot = make(box, 'nbdot');
    var hide = function () {
      tip.hidden = true;
      dot.hidden = true;
    };
    svg.addEventListener('pointerleave', hide);
    svg.addEventListener('pointermove', function (e) {
      var r = svg.getBoundingClientRect();
      var br = box.getBoundingClientRect();
      var k = r.width / d.w;
      var mx = (e.clientX - r.left) / k;
      var my = (e.clientY - r.top) / k;
      var at = function (x, y) {
        return [r.left - br.left + x * k, r.top - br.top + y * k];
      };
      tip.textContent = '';
      if (d.kind === 'pr') {
        var best = null;
        var dist = 24 * 24;
        d.series.forEach(function (s) {
          var p = s.data;
          for (var i = 0; i < p.recall.length; i++) {
            if (p.tp[i] + p.fp[i] === 0) continue;
            var x = b.left + p.recall[i] * iw;
            var y = b.top + (1 - p.precision[i]) * ih;
            var dd = (x - mx) * (x - mx) + (y - my) * (y - my);
            if (dd < dist) {
              dist = dd;
              best = { s: s, i: i, x: x, y: y };
            }
          }
        });
        if (!best) return hide();
        var p = best.s.data;
        var i = best.i;
        line(tip, best.s.name, best.s.color, 'nbtip-head');
        line(tip, 'Threshold ' + p.thresholds[i].toFixed(3));
        line(tip, 'Precision ' + p.precision[i].toFixed(3) + ' · recall ' + p.recall[i].toFixed(3));
        line(
          tip,
          'TP ' + count(p.tp[i]) + ' · FP ' + count(p.fp[i]) + ' · TN ' + count(p.tn[i]) + ' · FN ' + count(p.fn[i]),
          '',
          'nbtip-faint',
        );
        var pt = at(best.x, best.y);
        dot.style.left = pt[0] + 'px';
        dot.style.top = pt[1] + 'px';
        dot.style.background = best.s.color;
        dot.hidden = false;
        place(tip, box, pt[0], pt[1]);
        tip.hidden = false;
        return;
      }
      var v = d.lo + ((mx - b.left) / iw) * (d.hi - d.lo);
      if (v < d.lo || v > d.hi) return hide();
      line(tip, 'Value ' + num(v), '', 'nbtip-faint');
      d.series.forEach(function (s) {
        for (var j = 0; j < s.counts.length; j++) {
          if (v >= s.edges[j] && v <= s.edges[j + 1]) {
            var total =
              s.counts.reduce(function (a, c) {
                return a + c;
              }, 0) || 1;
            line(
              tip,
              s.name +
                ': ' +
                num(s.edges[j]) +
                ' to ' +
                num(s.edges[j + 1]) +
                ' · ' +
                count(s.counts[j]) +
                ' (' +
                ((s.counts[j] / total) * 100).toFixed(1) +
                '%)',
              s.color,
            );
            return;
          }
        }
      });
      var q = at(mx, b.top + 8);
      place(tip, box, q[0], q[1]);
      tip.hidden = false;
    });
  });

  // Line charts (uPlot): every series' value at the cursor, best first; a click pins it
  window.nbLineTip = function (u, el, d, mains, color) {
    el.style.position = 'relative';
    var tip = make(el, 'nbtip');
    var pinned = false;
    var fmtX = function (x) {
      if (d.xKind === 'time') return new Date(x * 1000).toLocaleString();
      if (d.xKind === 'relative' || d.xKind === 'active') {
        var s = Math.round(x);
        var h = Math.floor(s / 3600);
        var m = Math.floor((s % 3600) / 60);
        return (h ? h + 'h ' : '') + (h || m ? m + 'm ' : '') + (s % 60) + 's';
      }
      if (d.xKind && d.xKind.indexOf('metric:') === 0) return d.xKind.slice(7) + ' ' + num(x);
      return 'Step ' + Math.round(x).toLocaleString();
    };
    // the nearest logged value of a series around row `idx` (joined tables leave gaps)
    var near = function (col, idx) {
      for (var k = 0; k < 400; k++) {
        if (col[idx - k] != null) return col[idx - k];
        if (col[idx + k] != null) return col[idx + k];
      }
      return null;
    };
    var show = function () {
      var idx = u.cursor.idx;
      if (idx == null) {
        tip.hidden = true;
        return;
      }
      tip.textContent = '';
      line(tip, fmtX(u.data[0][idx]) + (pinned ? ' · pinned' : ''), '', 'nbtip-head');
      var rows = mains
        .map(function (m) {
          var val = near(u.data[m.i], idx);
          var lo = m.lo >= 0 ? near(u.data[m.lo], idx) : null;
          var hi = m.hi >= 0 ? near(u.data[m.hi], idx) : null;
          return { label: m.label, c: m.c, v: val, lo: lo, hi: hi };
        })
        .filter(function (r) {
          return r.v != null;
        })
        .sort(function (a, b) {
          return d.lower ? a.v - b.v : b.v - a.v;
        });
      rows.slice(0, 15).forEach(function (r) {
        var extra = r.lo != null && r.hi != null && r.lo !== r.hi ? '  (' + num(r.lo) + ' to ' + num(r.hi) + ')' : '';
        line(tip, r.label + '  ' + num(r.v) + extra, color(r.c));
      });
      if (rows.length > 15) line(tip, '+' + (rows.length - 15) + ' more', '', 'nbtip-faint');
      place(tip, el, u.cursor.left + u.bbox.left / devicePixelRatio, 12);
      tip.hidden = false;
    };
    u.over.addEventListener('click', function () {
      pinned = !pinned && u.cursor.idx != null;
      tip.classList.toggle('nbtip-pin', pinned);
      show();
    });
    u.over.addEventListener('pointerleave', function () {
      if (!pinned) tip.hidden = true;
    });
    return function () {
      if (!pinned) show();
    };
  };
})();
