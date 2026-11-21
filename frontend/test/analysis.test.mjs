import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'

const vite = await createServer({
  configFile: false,
  optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true, ws: false },
  appType: 'custom',
})
after(() => vite.close())
const { attribution, fixtureDefinitions, metricList, pivotRows } = await vite.ssrLoadModule('/src/fixtures.ts')
const { demoPeriod, number } = await vite.ssrLoadModule('/src/model.ts')
const { validateDefinition } = await vite.ssrLoadModule('/src/formula.ts')
const { readSse } = await vite.ssrLoadModule('/src/client.ts')
const { remoteMetric, remoteScenario } = await vite.ssrLoadModule('/src/remote.ts')

test('demo scenarios close to the observed change and their channel totals agree', () => {
  for (const baseline of ['mom', 'yoy', 'target']) {
    const metrics = metricList({ ...demoPeriod, baseline, domain: 'all' })
    for (const metric of metrics.filter(item => ['gmv', 'margin'].includes(item.id))) {
      const result = attribution(metric)
      assert.ok(Math.abs(result.drivers.reduce((sum, driver) => sum + driver.value, 0) - metric.delta) <= 1e-9)
      assert.ok(Math.abs(result.residual) <= 1e-9)
      const rows = pivotRows({ metric }, 'channel', [])
      assert.ok(Math.abs(rows.reduce((sum, row) => sum + row.delta, 0) - metric.delta) <= .03)
      if (metric.id === 'gmv') {
        assert.ok(Math.abs(result.drivers.reduce((product, driver) => product * driver.current, .01) - metric.current) <= 1e-9)
      }
    }
  }
  assert.equal(number(-124000, '元', true), '−¥124,000')
  assert.equal(number(-2.7, ' pp', true), '-2.7 pp')
  assert.equal(number(null, '%'), '—')
})

test('metric formulas validate unit algebra, syntax, formula references and hierarchy cycles', () => {
  const gmv = fixtureDefinitions.find(item => item.id === 'gmv')
  assert.doesNotThrow(() => validateDefinition(gmv, fixtureDefinitions))
  assert.throws(() => validateDefinition({ ...gmv, formula: 'visitors + basket' }, fixtureDefinitions), /单位/)
  assert.throws(() => validateDefinition({ ...gmv, formula: '(visitors * basket' }, fixtureDefinitions), /括号/)
  assert.throws(() => validateDefinition({ ...gmv, formula: 'gmv' }, fixtureDefinitions), /循环依赖/)
  assert.throws(() => validateDefinition({ ...gmv, parentId: 'visitors' }, fixtureDefinitions), /层级存在循环/)
})

test('SSE parser spans CRLF frames and multibyte UTF-8 split across chunks', async () => {
  const payload = 'id: 6\r\nevent: step\r\ndata: {"analysis":{"title":"统计检验"}}\r\n\r\n: heartbeat\n\nid: 7\nevent: complete\ndata: {"analysis":{"title":"完成"}}'
  const bytes = new TextEncoder().encode(payload)
  const reader = new ReadableStream({
    start(controller) {
      for (let index = 0; index < bytes.length; index += 2) controller.enqueue(bytes.slice(index, index + 2))
      controller.close()
    },
  })
  const events = []
  for await (const event of readSse(reader)) events.push([event.id, event.type, event.payload.analysis.title])
  assert.deepEqual(events, [[6, 'step', '统计检验'], [7, 'complete', '完成']])
})

test('live API preserves ratio units and missing observations', () => {
  const raw = { metric_id: 'net_margin', name: '净利率', formula: 'profit / revenue', domain_id: 'fmcg', unit: 'ratio', threshold: .05, baseline_value: .2, current_value: .15, delta: -.05, delta_rate: -.25, anomaly: true, trend: [{ day: '2025-06-19', value: null }] }
  const metric = remoteMetric(raw)
  assert.equal(metric.current, 15)
  assert.equal(metric.delta, -5)
  assert.equal(metric.rate, -25)
  assert.deepEqual(metric.trend, [null])
  assert.equal(remoteMetric({ ...raw, current_value: null }).available, false)
  const scenario = remoteScenario({ id: 'scenario', name: '情景 A', estimate: .17, delta: .02, interval_80: [.16, .18], changes: { materials: -.1 }, sensitivity_curves: { materials: [{ change: -.1, estimate: .17 }] } }, '%')
  assert.equal(scenario.estimate, 17)
  assert.deepEqual([scenario.low, scenario.high], [16, 18])
  assert.equal(scenario.params.materials, -10)
})
