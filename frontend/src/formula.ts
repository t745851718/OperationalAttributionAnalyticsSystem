import type { MetricDefinition } from './model'

type Unit = [currency: number, count: number]
const units: Record<string, Unit> = { '元': [1, 0], '人': [0, 1], '单': [0, 1], '件': [0, 1], '%': [0, 0], '元/单': [1, -1], '无量纲': [0, 0] }
const identifier = /^[a-zA-Z_][a-zA-Z_0-9]*$/
export const unitOptions = Object.keys(units)
export const references = (formula: string) => [...new Set(formula.match(/[A-Za-z_][A-Za-z_0-9]*/g) ?? [])]
const same = (a: Unit, b: Unit) => a[0] === b[0] && a[1] === b[1]

function evaluateUnits(formula: string, resolve: (id: string) => Unit): Unit {
  const normalized = formula.replaceAll('×', '*').replaceAll('÷', '/').replaceAll('−', '-').replace(/\s/g, '')
  const tokens = normalized.match(/[a-zA-Z_][a-zA-Z_0-9]*|\d+(?:\.\d+)?|[+*/()-]/g) ?? []
  if (tokens.join('') !== normalized) throw new Error('公式含有无效字符。')
  let pointer = 0
  function operand(): Unit {
    const token = tokens[pointer++]
    if (token === '-' || token === '+') return operand()
    if (token === '(') {
      const result = sum()
      if (tokens[pointer++] !== ')') throw new Error('公式括号不匹配。')
      return result
    }
    if (token && identifier.test(token)) return resolve(token)
    if (token && /^\d/.test(token)) return [0, 0]
    throw new Error('公式缺少指标引用或数值。')
  }
  function product(): Unit {
    let a = operand()
    while (tokens[pointer] === '*' || tokens[pointer] === '/') {
      const sign = tokens[pointer++] === '*' ? 1 : -1
      const b = operand()
      a = [a[0] + sign * b[0], a[1] + sign * b[1]]
    }
    return a
  }
  function sum(): Unit {
    const a = product()
    while (tokens[pointer] === '+' || tokens[pointer] === '-') {
      pointer++
      if (!same(a, product())) throw new Error('加减运算的指标单位必须一致。')
    }
    return a
  }
  const result = sum()
  if (pointer !== tokens.length) throw new Error('请在指标引用之间添加运算符。')
  return result
}

export function validateDefinition(draft: MetricDefinition, definitions: MetricDefinition[]) {
  if (!draft.name.trim()) throw new Error('请输入指标名称。')
  const all = [...definitions.filter(item => item.id !== draft.id), draft]
  const byId = new Map(all.map(item => [item.id, item]))
  for (const definition of all) {
    const hierarchy = new Set([definition.id])
    let parent = definition.parentId
    while (parent) {
      if (hierarchy.has(parent)) throw new Error('指标层级存在循环。')
      hierarchy.add(parent)
      const node = byId.get(parent)
      if (!node || node.domain !== definition.domain) throw new Error('父级指标必须属于同一指标域。')
      parent = node.parentId
    }
    if (!definition.formula.trim()) {
      if (definition.type !== '原子') throw new Error(`「${definition.name}」需要拆解公式。`)
      continue
    }
    const visited = new Set([definition.id])
    function resolve(id: string): Unit {
      if (visited.has(id)) throw new Error('公式存在循环依赖。')
      const target = byId.get(id)
      if (!target || target.domain !== definition.domain) throw new Error(`未知或跨域指标引用：${id}`)
      visited.add(id)
      if (target.formula.trim()) evaluateUnits(target.formula, resolve)
      visited.delete(id)
      return units[target.unit] ?? [0, 0]
    }
    const expected = units[definition.unit]
    if (!expected || !same(expected, evaluateUnits(definition.formula, resolve))) throw new Error(`「${definition.name}」的公式结果与指标单位不一致。`)
  }
}
