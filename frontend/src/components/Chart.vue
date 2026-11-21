<script setup lang="ts">
import { onMounted, onBeforeUnmount, shallowRef, watch } from 'vue'
import { init, use, type EChartsType, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, CustomChart, LineChart, SankeyChart, ScatterChart, TreeChart } from 'echarts/charts'
import { AriaComponent, GridComponent, LegendComponent, MarkAreaComponent, TooltipComponent } from 'echarts/components'
import { theme } from '../context'

use([CanvasRenderer, BarChart, CustomChart, LineChart, SankeyChart, ScatterChart, TreeChart, AriaComponent, GridComponent, LegendComponent, MarkAreaComponent, TooltipComponent])
const props = defineProps<{ option: EChartsCoreOption; label: string; height?: number }>()
const emit = defineEmits<{ select: [id: string] }>()
const element = shallowRef<HTMLDivElement>()
let chart: EChartsType | undefined
let observer: ResizeObserver | undefined
function render() {
  chart?.setOption({ animationDuration: 300, textStyle: { fontFamily: 'inherit', color: theme.value === 'dark' ? '#d4d9ec' : '#535d75' }, ...props.option }, { notMerge: true })
}
onMounted(() => {
  if (!element.value) return
  chart = init(element.value)
  chart.on('click', event => {
    const id = (event.data as { id?: string })?.id
    if (id) emit('select', id)
  })
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(element.value)
  render()
})
watch([() => props.option, theme], render)
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>

<template><div ref="element" role="img" :aria-label="label" class="chart" :style="{ height: `${height ?? 280}px` }"></div></template>
