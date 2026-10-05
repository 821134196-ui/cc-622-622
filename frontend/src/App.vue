<template>
  <div>
    <header class="topbar">
      <div class="topbar-inner">
        <span class="brand">📚 样书寄送与作者签收系统</span>
        <nav>
          <RouterLink to="/todos">待办</RouterLink>
          <RouterLink to="/tasks">寄送任务</RouterLink>
          <RouterLink to="/authors">作者与地址</RouterLink>
          <RouterLink to="/books">图书与版次</RouterLink>
        </nav>
      </div>
    </header>
    <main class="container">
      <RouterView />
    </main>
  </div>
</template>
