import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './styles.css'
import TodoView from './views/TodoView.vue'
import TasksView from './views/TasksView.vue'
import TaskDetailView from './views/TaskDetailView.vue'
import AuthorsView from './views/AuthorsView.vue'
import BooksView from './views/BooksView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/todos' },
    { path: '/todos', component: TodoView },
    { path: '/tasks', component: TasksView },
    { path: '/tasks/:id', component: TaskDetailView, props: true },
    { path: '/authors', component: AuthorsView },
    { path: '/books', component: BooksView },
  ],
})

createApp(App).use(router).mount('#app')
