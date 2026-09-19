import { createRouter, createWebHistory } from 'vue-router'

import ProjectHome from '../views/ProjectHome.vue'
import WorkspaceView from '../views/WorkspaceView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'project-home',
      component: ProjectHome,
    },
    {
      path: '/workspace',
      name: 'workspace',
      component: WorkspaceView,
    },
  ],
})

export default router
