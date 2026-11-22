import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'
import ControlledSharingView from '@/views/ControlledSharingView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 固定路径必须在动态模块路由之前，否则会被 /:moduleKey 抢占。
    { path: '/controlled_sharing', name: 'controlled-sharing', component: ControlledSharingView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
