<script>
  import { onMount } from 'svelte'
  import { api, getToken, getRole, clearAuth } from './api.js'
  import Soak from './Soak.svelte'

  let username = localStorage.getItem('herb_user') || 'processor'
  let password = 'herb123456'
  let token = getToken()
  let role = getRole()
  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let error = ''
  let view = location.hash === '#/soak' ? 'soak' : 'records'

  function onHash() {
    view = location.hash === '#/soak' ? 'soak' : 'records'
  }

  onMount(() => {
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  })

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    token = data.access_token
    role = data.role
    username = data.username
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    localStorage.setItem('herb_user', username)
    await load()
  }

  async function load() {
    rows = await api('/api/batches')
  }

  async function save() {
    error = ''
    try {
      await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          herb,
          steps: [{ name: '清炒', temp_c: Number(tempC), minutes: Number(minutes) }],
        }),
      })
      await load()
    } catch (err) {
      error = err.message
    }
  }

  function leave() {
    clearAuth()
    token = ''
    role = ''
  }

  if (token) load()
</script>

<main>
  {#if !token}
    <h1>饮片炮制记录台</h1>
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。清炒前须先在浸泡台完成浸泡登记。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <span class="brand">饮片炮制记录台</span>
      <a href="#/" class:active={view === 'records'}>记录台</a>
      <a href="#/soak" class:active={view === 'soak'}>浸泡台</a>
      <span class="gap"></span>
      <span class="who">{username} · {role === 'writer' ? '炮制员' : '质检员'}</span>
      <button on:click={leave}>退出</button>
    </nav>

    {#if view === 'soak'}
      <Soak {role} />
    {:else}
      <h1>记录台</h1>
      {#if role === 'writer'}
        <p>
          <input bind:value={herb} placeholder="饮片" />
          <input type="number" bind:value={tempC} />
          <input type="number" bind:value={minutes} />
          <button on:click={save}>写入清炒记录</button>
        </p>
        {#if error}
          <p class="error">{error} <a href="#/soak">前往浸泡台</a></p>
        {/if}
      {/if}
      <ul>
        {#each rows as row}
          <li>{row.herb} · {row.verdict} · {row.reason} · 温度 {row.doc.steps[0].temp_c}</li>
        {/each}
      </ul>
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 720px; margin: 24px auto; color: #3f2f1f; }
  h1 { color: #7c2d12; }
  input { margin-right: 8px; padding: 6px; }
  .topbar {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 14px;
    background: #f3eadf;
    border: 1px solid #d8c9b8;
    border-radius: 6px;
  }
  .topbar .brand { font-weight: bold; color: #7c2d12; }
  .topbar a { color: #6b5d4f; text-decoration: none; padding: 4px 8px; border-radius: 4px; }
  .topbar a.active { background: #7c2d12; color: #fff; }
  .topbar .gap { flex: 1; }
  .topbar .who { color: #6b5d4f; font-size: 14px; }
  .error { color: #b91c1c; }
</style>
