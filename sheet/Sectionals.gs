/**
 * Sectionals.gs  (v63)
 *
 * Run sa63Install ONCE from the editor. It is safe to run again; it rewrites only its own cells.
 * 1. Daily Breakdown summary: adds accuracy columns X:AA (LOD 1 %, LOD 2 %, LOD 3 %, Overall %)
 *    next to the existing "SUMMARY — TOTAL DONE" counts in R:V.
 *    Accuracy = right ÷ (right + wrong), the same rule as Chapter Progress.
 * 2. New "Sectionals" tab: live formulas over the Mocks tab (rows with Source = Sectional).
 *    Mocks keeps every paper; Sectionals shows only sectionals. Both update together, with no sync step.
 *
 * Touches nothing else: no existing cell, header, tab or action is changed.
 * All formulas recalculate on their own. No triggers, no redeploy.
 */
function sa63Install() {
  var ss = SpreadsheetApp.getActive();
  var a = sa63Accuracy_(ss);
  var b = sa63Sectionals_(ss);
  var msg = 'Done. ' + a + ' ' + b;
  Logger.log(msg);
  return msg;
}

/* ---------- 1. accuracy beside the Daily Breakdown summary ---------- */
function sa63Accuracy_(ss) {
  var sh = ss.getSheetByName('Daily Breakdown');
  if (!sh) throw new Error('No "Daily Breakdown" tab.');
  if (String(sh.getRange('R4').getValue()).trim() !== 'Topic') throw new Error('Daily Breakdown R4 is not "Topic". Summary has moved; nothing written.');
  if (sh.getMaxColumns() < 27) sh.insertColumnsAfter(sh.getMaxColumns(), 27 - sh.getMaxColumns());

  var last = sh.getLastRow(), labels = sh.getRange(1, 18, last, 1).getValues(), end = 0;
  for (var r = 5; r <= last; r++) if (String(labels[r - 1][0]).trim() === 'GRAND TOTAL') { end = r; break; }
  if (!end) throw new Error('Could not find the GRAND TOTAL row in column R.');

  // refuse to overwrite anything that is not ours
  var mine = String(sh.getRange('X4').getValue()) === 'LOD 1 %';
  if (!mine) {
    var cur = sh.getRange(3, 24, end - 2, 4).getValues();
    if (cur.some(function (row) { return row.some(function (v) { return v !== ''; }); })) throw new Error('Daily Breakdown X3:AA' + end + ' is not empty. Nothing written.');
  }

  var DL = "'Daily Log'!", K = DL + '$K$5:$K', L = DL + '$L$5:$L', E = DL + '$E$5:$E', G = DL + '$G$5:$G', I = DL + '$I$5:$I';
  var LODS = [['LOD 1', 'Easy'], ['LOD 2', 'Medium'], ['LOD 3', 'Hard']];
  function crit(sec, topicRef, diffs) {
    // one SUMIFS per (column, diff label) so old Easy/Medium/Hard rows still count
    var parts = { k: [], l: [] };
    diffs.forEach(function (d) {
      var c = (sec ? ',' + E + ',"' + sec + '"' : '') + (topicRef ? ',' + G + ',' + topicRef : '') + ',' + I + ',"' + d + '"';
      parts.k.push('SUMIFS(' + K + c + ')');
      parts.l.push('SUMIFS(' + L + c + ')');
    });
    return '=LET(rt,' + parts.k.join('+') + ',wr,' + parts.l.join('+') + ',IF(rt+wr=0,"",rt/(rt+wr)))';
  }

  var out = [], sec = '';
  for (var row = 5; row <= end; row++) {
    var lab = String(labels[row - 1][0]).trim(), f = ['', '', '', ''];
    if (lab === 'QA' || lab === 'VA' || lab === 'DI') { sec = lab; f = sa63Row_(crit, sec, null, LODS); }
    else if (lab === 'GRAND TOTAL') f = sa63Row_(crit, null, null, LODS);
    else if (lab && sec) f = sa63Row_(crit, sec, '$R' + row, LODS);
    out.push(f);
  }

  sh.getRange('X3').setValue('ACCURACY  ·  right ÷ (right + wrong)').setFontWeight('bold');
  sh.getRange('S4:V4').copyFormatToRange(sh, 24, 27, 4, 4);
  sh.getRange('X4:AA4').setValues([['LOD 1 %', 'LOD 2 %', 'LOD 3 %', 'Overall %']]);
  var body = sh.getRange(5, 24, end - 4, 4);
  body.setFormulas(out).setNumberFormat('0%').setHorizontalAlignment('center');
  for (var c = 24; c <= 27; c++) sh.setColumnWidth(c, 80);

  // colour: under 50% red, 50–69% amber, 70%+ green (same thresholds as the runner)
  var a1 = body.getA1Notation(), keep = sh.getConditionalFormatRules().filter(function (rule) {
    return !rule.getRanges().some(function (rg) { return rg.getA1Notation() === a1; });
  });
  keep.push(SpreadsheetApp.newConditionalFormatRule().whenNumberLessThan(0.5).setFontColor('#c62828').setRanges([body]).build());
  keep.push(SpreadsheetApp.newConditionalFormatRule().whenNumberBetween(0.5, 0.6999).setFontColor('#b26a00').setRanges([body]).build());
  keep.push(SpreadsheetApp.newConditionalFormatRule().whenNumberGreaterThanOrEqualTo(0.7).setFontColor('#2e7d32').setRanges([body]).build());
  sh.setConditionalFormatRules(keep);
  return 'Daily Breakdown: accuracy added in X4:AA' + end + '.';
}
function sa63Row_(crit, sec, ref, LODS) {
  var all = [];
  LODS.forEach(function (p) { all = all.concat(p); });
  return LODS.map(function (p) { return crit(sec, ref, p); }).concat([crit(sec, ref, all)]);
}

/* ---------- 2. Sectionals tab (live view of Mocks where Source = Sectional) ---------- */
function sa63Sectionals_(ss) {
  var mk = ss.getSheetByName('Mocks');
  if (!mk) throw new Error('No "Mocks" tab. Run mkSetup first.');
  var hd = mk.getRange('A4:V4').getValues()[0];
  var need = { 0: 'Mock', 1: 'Date', 2: 'Section', 4: 'Q#', 5: 'Topic', 6: 'LOD', 8: 'Result', 11: 'Time', 13: 'Failure', 18: 'Secs', 19: 'Marks', 21: 'Source' };
  for (var i in need) if (String(hd[i]).trim() !== need[i]) throw new Error('Mocks column ' + String.fromCharCode(65 + (+i)) + '4 is "' + hd[i] + '", expected "' + need[i] + '". Nothing written.');

  var sh = ss.getSheetByName('Sectionals');
  if (sh && String(sh.getRange('A1').getValue()) !== 'SECTIONALS') throw new Error('A "Sectionals" tab already exists and is not mine. Rename it and run again.');
  if (!sh) sh = ss.insertSheet('Sectionals', ss.getSheetByName('Mock Analysis') ? ss.getSheetByName('Mock Analysis').getIndex() : ss.getNumSheets());
  sh.clear();
  if (sh.getMaxColumns() < 23) sh.insertColumnsAfter(sh.getMaxColumns(), 23 - sh.getMaxColumns());

  var M = 'Mocks!', A = M + '$A$5:$A', B = M + '$B$5:$B', C = M + '$C$5:$C', Ir = M + '$I$5:$I', S = M + '$S$5:$S', T = M + '$T$5:$T', V = M + '$V$5:$V';
  sh.getRange('A1').setValue('SECTIONALS').setFontSize(14).setFontWeight('bold');
  sh.getRange('A2').setValue('Live from the Mocks tab: every paper imported with Source = Sectional. Import on Mock Import as usual; it shows on Mocks and here at the same time. Score = CAT marking (+3, −1 MCQ, 0 TITA).');

  // by section
  sh.getRange('A4').setValue('BY SECTION').setFontWeight('bold');
  sh.getRange('A5:H5').setValues([['Section', 'Sectionals', 'Attempted', 'Accuracy', 'Avg score', 'Best score', 'Last score', 'Last date']]);
  var secRows = [];
  ['DILR', 'QA', 'VARC'].forEach(function (lab, k) {
    var r = 6 + k, c = '$C$12:$C,$A' + r;
    secRows.push([lab,
      '=IFERROR(ROWS(FILTER($A$12:$A,$C$12:$C=$A' + r + ')),0)',
      '=SUMIFS($D$12:$D,' + c + ')',
      '=IF(C' + r + '=0,"",SUMIFS($E$12:$E,' + c + ')/C' + r + ')',
      '=IFERROR(AVERAGEIFS($I$12:$I,' + c + '),"")',
      '=IFERROR(MAX(FILTER($I$12:$I,$C$12:$C=$A' + r + ')),"")',
      '=IFERROR(INDEX(FILTER($I$12:$I,$C$12:$C=$A' + r + '),1),"")',
      '=IFERROR(INDEX(FILTER($B$12:$B,$C$12:$C=$A' + r + '),1),"")']);
  });
  sh.getRange(6, 1, 3, 8).setValues(secRows);
  sh.getRange('D6:D8').setNumberFormat('0%');

  // every sectional, newest first
  sh.getRange('A10').setValue('EVERY SECTIONAL  ·  newest first').setFontWeight('bold');
  sh.getRange('A11:J11').setValues([['Sectional', 'Date', 'Section', 'Attempted', 'Correct', 'Wrong', 'Skipped', 'Accuracy', 'Score', 'Time used (min)']]);
  sh.getRange('A12').setFormula(
    '=IFERROR(LET(m,' + A + ',v,' + V + ',n,UNIQUE(FILTER(m,v="Sectional",m<>"")),' +
    'd,MAP(n,LAMBDA(x,INDEX(FILTER(' + B + ',m=x,v="Sectional"),1))),' +
    's,MAP(n,LAMBDA(x,LET(z,INDEX(FILTER(' + C + ',m=x,v="Sectional"),1),IF(z="DI","DILR",IF(z="VA","VARC",z))))),' +
    'c,MAP(n,LAMBDA(x,COUNTIFS(m,x,v,"Sectional",' + Ir + ',"Correct"))),w,MAP(n,LAMBDA(x,COUNTIFS(m,x,v,"Sectional",' + Ir + ',"Wrong"))),k,MAP(n,LAMBDA(x,COUNTIFS(m,x,v,"Sectional",' + Ir + ',"Skipped"))),' +
    'at,MAP(c,w,LAMBDA(p,q,p+q)),ac,MAP(c,w,LAMBDA(p,q,IF(p+q=0,"",p/(p+q)))),' +
    'sc,MAP(n,LAMBDA(x,SUMIFS(' + T + ',m,x,v,"Sectional"))),' +
    'tm,MAP(n,LAMBDA(x,ROUND(SUMIFS(' + S + ',m,x,v,"Sectional")/60,1))),' +
    'SORT(HSTACK(n,d,s,at,c,w,k,ac,sc,tm),2,FALSE)),"No sectionals yet. On Mock Import set Source = Sectional, then Import.")');
  sh.getRange('H12:H').setNumberFormat('0%');
  sh.getRange('B12:B').setNumberFormat('d mmm yyyy'); sh.getRange('H6:H8').setNumberFormat('d mmm yyyy'); sh.getRange('M12:M').setNumberFormat('d mmm yyyy');

  // every sectional question (key columns of Mocks)
  sh.getRange('L10').setValue('EVERY SECTIONAL QUESTION').setFontWeight('bold');
  sh.getRange('L11:U11').setValues([['Sectional', 'Date', 'Section', 'Q#', 'Topic', 'LOD', 'Result', 'Time', 'Marks', 'Failure']]);
  sh.getRange('L12').setFormula('=IFERROR(CHOOSECOLS(FILTER(' + M + '$A$5:$V,' + V + '="Sectional",' + A + '<>""),1,2,3,5,6,7,9,12,20,14),"")');

  [sh.getRange('A5:H5'), sh.getRange('A11:J11'), sh.getRange('L11:U11')].forEach(function (rg) { rg.setFontWeight('bold').setBackground('#e8eaf6'); });
  sh.setFrozenRows(0);
  sh.setColumnWidth(1, 190); sh.setColumnWidth(12, 190); sh.setColumnWidth(16, 210); sh.setColumnWidth(11, 24);
  return 'Sectionals tab ready.';
}
