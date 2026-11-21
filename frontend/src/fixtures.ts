import { type Metric, type Driver, type BusinessEvent, type Filter, type MetricDefinition, type Dimension, type Hypothesis, type Analysis, type PivotRow, type Slice, type ReportSection, number, dimensions, demoPeriod, rounded } from './model'

const metrics = [
  { id: 'gmv', name: 'GMV', description: '商品交易总额', domain: 'commerce', unit: '元', base: 1000000, value: 876000, yoy: 7.6, threshold: 8, trend: [970000, 1000000, 986000, 1014000, 990000, 1062000, 1000000, 943000, 967000, 910000, 930000, 876000] },
  { id: 'conversion', name: '支付转化率', description: '支付订单数 / 访客数', domain: 'commerce', unit: '%', base: 4.8, value: 4.18, yoy: -4.2, threshold: 8, trend: [4.78, 4.84, 4.72, 4.82, 4.7, 4.8, 4.64, 4.72, 4.49, 4.56, 4.34, 4.18] },
  { id: 'margin', name: '净利率', description: '净利润 / 营业收入', domain: 'fmcg', unit: '%', base: 18.3, value: 15.6, yoy: -9.8, threshold: 8, trend: [18, 18.8, 18.3, 18.6, 18.5, 19.1, 18.3, 17.4, 17.7, 16.6, 16.85, 15.6] },
  { id: 'revenue', name: '营业收入', description: '快消品渠道收入', domain: 'fmcg', unit: '元', base: 2140000, value: 2260000, yoy: 11.4, threshold: 8, trend: [2050000, 2080000, 2110000, 2070000, 2180000, 2140000, 2200000, 2160000, 2220000, 2210000, 2270000, 2260000] },
]

export function metricList(filter: Filter): Metric[] {
  const daysFromAnchor = Math.round((Date.parse(filter.end) - Date.parse(demoPeriod.end)) / 86400000)
  const dateShift = 1 + Math.max(-0.1, Math.min(0.1, daysFromAnchor * 0.003))
  return metrics.filter(metric => filter.domain === 'all' || filter.domain === metric.domain).map(metric => {
    const current = rounded(metric.value * dateShift)
    const previous = rounded((filter.baseline === 'yoy' ? metric.value / (1 + metric.yoy / 100) : metric.base * (filter.baseline === 'target' ? 1.045 : 1)) * dateShift)
    return { ...metric, current, previous, delta: rounded(current - previous), rate: previous ? rounded((current / previous - 1) * 100) : null, mom: rounded((metric.value / metric.base - 1) * 100), trend: metric.trend.map(value => rounded(value * dateShift)) }
  })
}

export const fixtureEvents: BusinessEvent[] = [
  { id: 'e-promo', title: '618 大促收官', type: '大促', domain: 'commerce', start: '2025-06-18', end: '2025-06-22', scope: ['自然搜索', '信息流'], note: '促销补贴与站内资源位陆续撤回，大促余量结束后访客需求回落。' },
  { id: 'e-stock', title: '美妆畅销 SKU 断货', type: '运营', domain: 'commerce', start: '2025-06-24', end: '2025-06-27', scope: ['美妆', '信息流'], note: '重点组合装可售库存不足，高客单价商品成交占比下降。' },
  { id: 'e-material', title: '原料采购价格调整', type: '宏观', domain: 'fmcg', start: '2025-06-23', end: '2025-06-29', scope: ['饮品', '华东'], note: '原材料新批次采用调价后的结算单价。' },
  { id: 'e-commission', title: '连锁渠道佣金调整', type: '政策', domain: 'fmcg', start: '2025-06-25', end: '2025-06-29', scope: ['连锁商超'], note: '连锁商超新佣金费率开始执行。' },
  { id: 'e-payment', title: '支付链路升级', type: '运营', domain: 'commerce', start: '2025-06-11', end: '2025-06-12', scope: ['全渠道'], note: '支付网关计划维护。' },
]

const definitions: [string, string, string, string, MetricDefinition['type'], MetricDefinition['model'], string, string | null][] = [
  ['gmv', 'GMV', 'commerce', '元', '复合', 'mul', 'visitors × conversion × basket', null],
  ['visitors', '访客数', 'commerce', '人', '原子', 'add', '', 'gmv'],
  ['conversion', '支付转化率', 'commerce', '%', '派生', 'mul', 'orders / visitors', 'gmv'],
  ['orders', '支付订单数', 'commerce', '单', '原子', 'add', '', 'conversion'],
  ['basket', '客单价', 'commerce', '元/单', '派生', 'mul', 'sales / orders', 'gmv'],
  ['sales', '成交金额', 'commerce', '元', '原子', 'add', '', 'basket'],
  ['margin', '净利率', 'fmcg', '%', '复合', 'mul', 'profit / revenue', null],
  ['profit', '净利润', 'fmcg', '元', '派生', 'add', 'revenue - raw - freight - commission', 'margin'],
  ['raw', '原料成本', 'fmcg', '元', '原子', 'add', '', 'profit'],
  ['freight', '物流履约', 'fmcg', '元', '原子', 'add', '', 'profit'],
  ['commission', '渠道佣金', 'fmcg', '元', '原子', 'add', '', 'profit'],
  ['revenue', '营业收入', 'fmcg', '元', '原子', 'add', '', 'margin'],
]
export const fixtureDefinitions: MetricDefinition[] = definitions.map(([id, name, domain, unit, type, model, formula, parentId], order) => ({ id, name, domain, unit, type, model, formula, parentId, order }))

const groups: Record<Dimension, [string[], string[]]> = {
  channel: [['信息流', '自然搜索', '站内推荐', '私域'], ['连锁商超', '经销渠道', '自营零售', '区域专卖']],
  region: [['华东', '华南', '华北', '西部'], ['华东', '华南', '华北', '西部']],
  category: [['美妆', '家居', '服饰', '数码'], ['饮品', '休闲食品', '日化', '生鲜']],
  segment: [['新客', '复购客', '高价值客', '沉睡客'], ['大众客群', '家庭客群', '企业客户', '高端客群']],
  date: [['06-23 至 06-24', '06-25 至 06-26', '06-27 至 06-28', '06-29'], ['06-23 至 06-24', '06-25 至 06-26', '06-27 至 06-28', '06-29']],
}

export function attribution(metric: Metric) {
  const isCommerce = metric.domain === 'commerce'
  const params: [string, string, number, number, number, string, number][] = isCommerce
    ? [['visitors', '流量回落', .46, 250000, 230000, '人', .097], ['conversion', '支付转化下降', .36, 4.8, 4.18, '%', .125], ['basket', '高客单成交减少', .18, 83.33, 81.6, '元', .08]]
    : [['raw', '原料成本上涨', .61, 845000, 890000, '元', -.3], ['commission', '渠道佣金调整', .31, 162000, 182000, '元', -.19], ['freight', '物流履约成本', .08, 94000, 99000, '元', -.08]]
  const gmvRatio = metric.id === 'gmv' && metric.previous > 0 && metric.current > 0 ? metric.current / metric.previous : undefined
  let allocated = 0
  const drivers: Driver[] = params.map(([id, name, fraction, previous, current, unit, sensitivity], index) => {
    const value = index === params.length - 1 ? rounded(metric.delta - allocated) : rounded(metric.delta * fraction)
    allocated += value
    const base = gmvRatio && id === 'basket' ? metric.previous / (250000 * .048) : previous
    const observed = gmvRatio ? base * gmvRatio ** fraction : current
    return { id, name, value, previous: base, current: observed, unit, sensitivity, adjustable: true, min: -20, max: 20 }
  })
  const tree = { id: metric.id, name: metric.name, previous: metric.previous, current: metric.current, unit: metric.unit, children: drivers.map(driver => ({
    id: driver.id, name: driver.name, current: driver.current, previous: driver.previous, unit: driver.unit,
    children: [{ id: `${driver.id}-detail`, name: isCommerce ? '重点渠道' : '重点品类', current: rounded(driver.current * .55), previous: rounded(driver.previous * .56), unit: driver.unit }],
  })) }
  return { drivers, tree, previous: metric.previous, current: metric.current, residual: rounded(metric.delta - allocated, 9), method: metric.id === 'gmv' ? 'LMDI 因子拆解' : '差额贡献拆解', sql: `SELECT period, SUM(${metric.id}_value) AS metric_value\nFROM demo_metric_snapshot\nWHERE metric_id = '${metric.id}' GROUP BY period;` }
}

export function pivotRows(analysis: Analysis, dimension: Dimension, slices: Slice[]): PivotRow[] {
  const metric = analysis.metric
  if (!metric) return []
  const side = metric.domain === 'commerce' ? 0 : 1
  const names = groups[dimension][side]
  const weights = [.52, .25, .16, .07]
  const narrowed = slices.reduce((share, slice) => {
    const index = groups[slice.dimension][side].indexOf(slice.value)
    return share * (weights[index] ?? .35)
  }, 1)
  const childDimension = dimension === 'channel' ? 'category' : 'channel'
  return names.map((label, index) => {
    const previous = rounded(metric.previous * narrowed * weights[index])
    const delta = rounded(metric.delta * narrowed * weights[index])
    const current = rounded(previous + delta)
    const id = `${dimension}-${index}`
    return { id, label, dimension, previous, current, delta, contribution: metric.delta ? rounded(delta / metric.delta * 100) : null,
      children: groups[childDimension][side].slice(0, 2).map((name, childIndex) => {
        const share = childIndex === 0 ? .65 : .35
        return { id: `${id}-${childIndex}`, label: name, dimension: childDimension, previous: rounded(previous * share), current: rounded(current * share), delta: rounded(delta * share), contribution: metric.delta ? rounded(delta * share / metric.delta * 100) : null }
      }),
    }
  })
}

export function analysisEvidence(analysis: Analysis, calendar: BusinessEvent[], pending = false) {
  const metric = analysis.metric
  const decomposition = analysis.decomposition
  if (!metric || !decomposition) return { hypotheses: [], conclusions: [], actions: [], events: [] }
  const commerce = metric.domain === 'commerce'
  const scope = analysis.slices.at(-1)?.value
  const isolatePromotion = commerce && analysis.messages.some(message => message.role === 'user' && /排除大促/.test(message.text))
  const statements = commerce
    ? ['大促收官后流量回落是 GMV 下滑的首要驱动', '高流量低转化渠道占比提升，拉低整体支付转化率', '畅销美妆断货减少高客单商品成交', '支付网关升级导致 GMV 下滑']
    : ['原料采购涨价压缩净利率', '连锁商超佣金率上升侵蚀净利润', '物流履约成本波动造成净利率显著下降', '区域需求下降导致成本率上升']
  const hypotheses: Hypothesis[] = statements.map((statement, index) => {
    const controlled = index === 0 && isolatePromotion
    const confirmed = !controlled && index < (commerce ? 3 : 2)
    const driver = decomposition.drivers[index]
    return {
      id: `hyp-${analysis.messageCount}-${index}`, statement: controlled ? '剔除大促窗口后，剩余流量差仍能独立解释 GMV 下滑' : scope ? `${scope} · ${statement}` : statement, driver: driver?.name ?? '对照因素',
      status: pending ? 'pending' : confirmed ? 'confirmed' : 'excluded',
      confidence: pending ? null : controlled ? .41 : [0.96, 0.88, commerce ? .79 : .42, .24][index],
      p: pending ? null : controlled ? .22 : [.0021, .013, commerce ? .038 : .19, .31][index],
      effect: pending ? null : controlled ? -.09 : [-.66, -.4, -.18, -.04][index],
      code: `-- 按维度与对比周期汇总检验输入\nSELECT ${analysis.dimension}, period, AVG(value) AS avg_value, COUNT(*) AS n\nFROM demo_observations\nWHERE metric_id = '${metric.id}'\nGROUP BY ${analysis.dimension}, period;`,
      elapsed: pending ? null : 83 + index * 24,
      output: pending ? '' : confirmed ? `分层方向一致，效应量达到阈值。贡献 ${number(driver?.value, metric.unit === '%' ? ' pp' : metric.unit, true)}。` : controlled ? '排除大促观察窗口后，流量差未达到检验阈值。全周期贡献保留在瀑布图。' : '控制时间趋势后的效应未达到检验阈值。',
    }
  })
  const events = calendar.filter(event => event.domain === metric.domain && (!isolatePromotion || event.type !== '大促') && Date.parse(event.end) >= Date.parse(analysis.period.start) - 259200000 && Date.parse(event.start) <= Date.parse(analysis.period.end) + 259200000)
  const conclusions = hypotheses.filter(hypothesis => hypothesis.status === 'confirmed').map((hypothesis, index) => ({
    id: hypothesis.id, title: hypothesis.statement, text: hypothesis.output,
    type: (index === 0 ? '首要原因' : '次要原因') as '首要原因' | '次要原因',
  }))
  const actions = decomposition.drivers.slice(0, 2).flatMap((driver, index) => isolatePromotion && index === 0 ? [] : [{
    id: driver.id, title: commerce ? ['恢复高转化渠道投放', '修复信息流转化漏斗'][index] : ['调整高成本原料采购批次', '复核渠道佣金与促销结算'][index],
    description: commerce ? ['优先恢复大促后流失的高价值自然与复购流量。', '跟踪高流量入口的承接页面与支付转化。'][index] : ['重新谈判采购量与交付批次，降低单位成本。', '对重点连锁商超按合同重新核算费率。'][index],
    driver: driver.name, owner: commerce ? ['增长运营', '渠道运营'][index] : ['采购负责人', '渠道负责人'][index],
    days: index === 0 ? 7 : 14, recovery: Math.round(Math.abs(driver.value) * .3 * (metric.unit === '%' ? 22600 : 1)),
  }])
  return { hypotheses, conclusions: [...conclusions, ...events.map(event => ({ id: event.id, title: event.title, text: event.note, type: '外部事件' as const, eventId: event.id }))], actions, events }
}

export function reportSections(analysis: Analysis, rows = pivotRows(analysis, analysis.dimension, analysis.slices)): ReportSection[] {
  const metric = analysis.metric
  const deltaUnit = metric?.unit === '%' ? ' pp' : metric?.unit
  return [
    { id: 'overview', title: '异动背景与问题定义', paragraphs: [`${analysis.period.start} 至 ${analysis.period.end}，${metric?.name ?? '目标指标'}由 ${number(metric?.previous, metric?.unit)} 变为 ${number(metric?.current, metric?.unit)}，差异 ${number(metric?.delta, deltaUnit, true)}（${number(metric?.rate, '%', true)}）。`] },
    { id: 'drivers', title: '因子贡献率拆解', paragraphs: [analysis.decomposition?.method ?? '暂无拆解'], headers: ['驱动因子', '绝对贡献', '贡献率（%）'], rows: analysis.decomposition?.drivers.map(driver => [driver.name, driver.value, metric?.delta ? rounded(driver.value / metric.delta * 100) : '—']) },
    { id: 'drill', title: '细分维度下钻证据', paragraphs: [`下钻维度 ${dimensions[analysis.dimension]}${analysis.slices.length ? ` · ${analysis.slices.map(slice => `${dimensions[slice.dimension]}=${slice.value}`).join(' / ')}` : ''}`], headers: ['维度', '基期值', '现期值', '差额'], rows: rows.map(row => [row.label, row.previous ?? '—', row.current ?? '—', row.delta]) },
    { id: 'conclusion', title: '核心归因结论', paragraphs: analysis.conclusions.map(item => `${item.type} · ${item.title}。 ${item.text}`) },
    { id: 'evidence', title: '因果证据链与检验置信度', paragraphs: analysis.hypotheses.map(item => `${item.statement}。 ${item.output}\n${item.code}`), headers: ['假设', '效应量', 'p 值', '置信度（%）'], rows: analysis.hypotheses.map(item => [item.statement, item.effect ?? '—', item.p ?? '—', item.confidence == null ? '—' : rounded(item.confidence * 100)]) },
    { id: 'whatif', title: 'What-If 情景模拟结论', paragraphs: analysis.scenarios.length ? ['以下区间为 80% 预测区间。'] : ['会话暂无已保存情景。'], headers: ['情景', '预测值', '区间下界', '区间上界'], rows: analysis.scenarios.map(item => [item.name, item.estimate, item.low, item.high]) },
    { id: 'actions', title: '落地策略行动清单', paragraphs: [], headers: ['优先级 / 行动', '驱动因子', '责任岗位', '周期（天）', '预期挽回（元）'], rows: analysis.actions.map((action, index) => [`${index + 1}. ${action.title}`, action.driver, action.owner, action.days, action.recovery]) },
  ]
}
