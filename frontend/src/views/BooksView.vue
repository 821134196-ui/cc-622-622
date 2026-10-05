<template>
  <div>
    <div class="card">
      <h2>新增图书</h2>
      <div class="form-row">
        <label>书名</label><input v-model="bookForm.title" style="width:200px" />
        <label>ISBN</label><input v-model="bookForm.isbn" style="width:180px" />
        <button class="primary" @click="addBook">添加</button>
      </div>
      <div v-if="error" class="error-banner">{{ error }}</div>
    </div>

    <div class="card">
      <h2>图书与版次</h2>
      <div v-if="books.length === 0" class="empty">暂无图书</div>
      <div v-for="b in books" :key="b.id" class="pkg-card">
        <div class="pkg-head">
          <span class="no">{{ b.title }}</span>
          <span class="tag">ISBN {{ b.isbn }}</span>
          <span v-for="e in b.editions" :key="e.id" class="badge blue">{{ e.edition_no }}</span>
        </div>
        <div class="form-row" style="margin-top:10px">
          <label>新版次</label>
          <input v-model="editionForms[b.id]" placeholder="如: 第3版" style="width:120px" />
          <button class="sm" @click="addEdition(b)">添加版次</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const books = ref([])
const error = ref('')
const bookForm = reactive({ title: '', isbn: '' })
const editionForms = reactive({})

async function load() {
  error.value = ''
  try {
    books.value = await api.get('/api/books')
  } catch (e) {
    error.value = e.message
  }
}

async function addBook() {
  error.value = ''
  try {
    await api.post('/api/books', { ...bookForm })
    bookForm.title = bookForm.isbn = ''
    await load()
  } catch (e) { error.value = e.message }
}

async function addEdition(b) {
  error.value = ''
  try {
    await api.post(`/api/books/${b.id}/editions`,
      { edition_no: editionForms[b.id] || '' })
    editionForms[b.id] = ''
    await load()
  } catch (e) { error.value = e.message }
}

onMounted(load)
</script>
