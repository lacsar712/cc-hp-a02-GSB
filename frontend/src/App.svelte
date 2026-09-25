<script>
  import { onDestroy } from 'svelte'

  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let error = ''

  let view = 'batches'
  let soaks = { targets: [], sessions: [] }
  let soakHerb = '白芍'
  let soakMinutes = 30
  let soakError = ''
  let soakTimer = null

  $: inProgress = soaks.sessions.filter((s) => !s.ready)
  $: readyList = soaks.sessions.filter((s) => s.ready)
  $: soakingHerbs = new Set(soaks.sessions.map((s) => s.herb))

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data
  }

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    token = data.access_token
    role = data.role
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    await load()
  }

  async function load() {
    rows = await api('/api/batches')
  }

  async function loadSoaks() {
    soaks = await api('/api/soaks')
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

  async function saveTarget() {
    soakError = ''
    try {
      await api('/api/soaks/target', {
        method: 'PUT',
        body: JSON.stringify({ herb: soakHerb, target_minutes: Number(soakMinutes) }),
      })
      await loadSoaks()
    } catch (err) {
      soakError = err.message
    }
  }

  async function startSoak(name) {
    soakError = ''
    try {
      await api('/api/soaks/start', {
        method: 'POST',
        body: JSON.stringify({ herb: name }),
      })
      await loadSoaks()
    } catch (err) {
      soakError = err.message
    }
  }

  function showBatches() {
    view = 'batches'
    stopSoakTimer()
  }

  async function showSoaks() {
    view = 'soaks'
    soakError = ''
    await loadSoaks()
    stopSoakTimer()
    soakTimer = setInterval(loadSoaks, 10000)
  }

  function stopSoakTimer() {
    if (soakTimer) {
      clearInterval(soakTimer)
      soakTimer = null
    }
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
    stopSoakTimer()
    view = 'batches'
  }

  function wholeMinutes(seconds) {
    return Math.floor(seconds / 60)
  }

  function minutesLeft(seconds) {
    return Math.ceil(seconds / 60)
  }

  onDestroy(stopSoakTimer)

  if (token) load()
</script>

<main>
  <h1>饮片炮制记录台</h1>
  {#if !token}
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。清炒前须先在浸泡台完成浸泡。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <a href="/" class:active={view === 'batches'} on:click|preventDefault={showBatches}>记录台</a>
      <a href="/soaks" class:active={view === 'soaks'} on:click|preventDefault={showSoaks}>浸泡台</a>
      <span class="who">{username}（{role === 'writer' ? '炮制员' : '质检员'}）</span>
      <button on:click={leave}>退出</button>
    </nav>

    {#if view === 'batches'}
      {#if role === 'writer'}
        <input bind:value={herb} placeholder="饮片" />
        <input type="number" bind:value={tempC} />
        <input type="number" bind:value={minutes} />
        <button on:click={save}>写入清炒记录</button>
        {#if error}<p class="err">{error}</p>{/if}
      {/if}
      <ul>
        {#each rows as row}
          <li>{row.herb} · {row.verdict} · {row.reason} · 温度 {row.doc.steps[0].temp_c}</li>
        {/each}
      </ul>
    {:else}
      <section>
        <h2>目标设置</h2>
        {#if role === 'writer'}
          <input bind:value={soakHerb} placeholder="饮片" />
          <input type="number" min="0" bind:value={soakMinutes} /> 分钟
          <button on:click={saveTarget}>保存目标</button>
        {/if}
        {#if soaks.targets.length === 0}
          <p>尚未设置任何浸泡目标。</p>
        {:else}
          <ul>
            {#each soaks.targets as t}
              <li>
                {t.herb} · 目标 {t.target_minutes} 分钟
                {#if role === 'writer' && !soakingHerbs.has(t.herb)}
                  <button on:click={() => startSoak(t.herb)}>开始浸泡</button>
                {/if}
                {#if soakingHerbs.has(t.herb)}<span class="tag">浸泡中</span>{/if}
              </li>
            {/each}
          </ul>
        {/if}
      </section>

      <section>
        <h2>进行中进度</h2>
        {#if inProgress.length === 0}
          <p>暂无进行中的浸泡。</p>
        {:else}
          <ul>
            {#each inProgress as s}
              <li>
                {s.herb} · 目标 {s.target_minutes} 分钟 · 已泡 {wholeMinutes(s.elapsed_seconds)} 分钟 ·
                还差 {minutesLeft(s.remaining_seconds)} 分钟
              </li>
            {/each}
          </ul>
        {/if}
      </section>

      <section>
        <h2>已满可写清单</h2>
        {#if readyList.length === 0}
          <p>暂无浸泡已满的饮片。</p>
        {:else}
          <ul>
            {#each readyList as s}
              <li>{s.herb} · 目标 {s.target_minutes} 分钟 · 浸泡已满，可开炒</li>
            {/each}
          </ul>
        {/if}
      </section>

      {#if soakError}<p class="err">{soakError}</p>{/if}
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 720px; margin: 24px auto; color: #3f2f1f; }
  h1 { color: #7c2d12; }
  h2 { color: #7c2d12; font-size: 18px; margin-bottom: 8px; }
  input { margin-right: 8px; padding: 6px; }
  section { border-top: 1px solid #e5d9c8; padding: 12px 0; }
  .topbar { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
  .topbar a { color: #7c2d12; text-decoration: none; padding-bottom: 2px; }
  .topbar a.active { font-weight: bold; border-bottom: 2px solid #7c2d12; }
  .topbar .who { margin-left: auto; color: #8a7358; }
  .err { color: #b91c1c; }
  .tag { color: #8a7358; font-size: 12px; margin-left: 8px; }
</style>
