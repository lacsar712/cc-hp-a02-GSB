<script>
  import { onMount, onDestroy } from 'svelte'
  import { api } from './api.js'

  export let role = 'reader'

  let targets = []
  let active = []
  let herb = ''
  let targetMinutes = 30
  let error = ''
  let notice = ''
  let timer = null

  $: writer = role === 'writer'
  $: activeHerbs = new Set(active.map((s) => s.herb))
  $: inProgress = active.filter((s) => !s.ready)
  $: ready = active.filter((s) => s.ready)

  async function load() {
    try {
      const data = await api('/api/soaks')
      targets = data.targets
      active = data.active
    } catch (err) {
      error = err.message
    }
  }

  async function setTarget() {
    error = ''
    notice = ''
    try {
      await api('/api/soaks/targets', {
        method: 'PUT',
        body: JSON.stringify({ herb: herb.trim(), target_minutes: Number(targetMinutes) }),
      })
      notice = `已记下 ${herb.trim()} 的浸泡目标 ${Number(targetMinutes)} 分钟`
      await load()
    } catch (err) {
      error = err.message
    }
  }

  async function start(name) {
    error = ''
    notice = ''
    try {
      await api('/api/soaks/start', {
        method: 'POST',
        body: JSON.stringify({ herb: name }),
      })
      notice = `${name} 已开始浸泡，以服务器时刻计时`
      await load()
    } catch (err) {
      error = err.message
    }
  }

  function fmtTime(iso) {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour12: false })
  }

  onMount(() => {
    load()
    timer = setInterval(load, 5000)
  })
  onDestroy(() => clearInterval(timer))
</script>

<section>
  <h2>浸泡台</h2>
  <p class="hint">清炒前须先完成浸泡登记：设目标分钟，点开始浸泡，以服务器时刻计时，泡满目标分钟方可开炒。</p>

  {#if error}<p class="error">{error}</p>{/if}
  {#if notice}<p class="notice">{notice}</p>{/if}

  <h3>目标设置</h3>
  {#if writer}
    <p>
      <input bind:value={herb} placeholder="饮片，如 白芍" />
      <input type="number" min="0" bind:value={targetMinutes} />
      <button on:click={setTarget} disabled={!herb.trim()}>设置目标分钟</button>
    </p>
  {/if}
  {#if targets.length === 0}
    <p class="empty">尚未设置任何浸泡目标。</p>
  {:else}
    <table>
      <thead>
        <tr><th>饮片</th><th>目标分钟</th><th>设置人</th><th></th></tr>
      </thead>
      <tbody>
        {#each targets as t}
          <tr>
            <td>{t.herb}</td>
            <td>{t.target_minutes}</td>
            <td>{t.updated_by}</td>
            <td>
              {#if writer}
                <button on:click={() => start(t.herb)} disabled={activeHerbs.has(t.herb)}>
                  {activeHerbs.has(t.herb) ? '浸泡中' : '开始浸泡'}
                </button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <h3>进行中进度</h3>
  {#if inProgress.length === 0}
    <p class="empty">暂无进行中的浸泡。</p>
  {:else}
    <table>
      <thead>
        <tr><th>饮片</th><th>目标分钟</th><th>开始时刻</th><th>已泡分钟</th><th>还差分钟</th></tr>
      </thead>
      <tbody>
        {#each inProgress as s}
          <tr>
            <td>{s.herb}</td>
            <td>{s.target_minutes}</td>
            <td>{fmtTime(s.started_at)}</td>
            <td>{s.elapsed_minutes}</td>
            <td class="remain">{s.remaining_minutes}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <h3>已满可写清单</h3>
  {#if ready.length === 0}
    <p class="empty">暂无已泡满的饮片。</p>
  {:else}
    <table>
      <thead>
        <tr><th>饮片</th><th>目标分钟</th><th>开始时刻</th><th>状态</th></tr>
      </thead>
      <tbody>
        {#each ready as s}
          <tr>
            <td>{s.herb}</td>
            <td>{s.target_minutes}</td>
            <td>{fmtTime(s.started_at)}</td>
            <td class="ok">已泡满，可开炒</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  section { margin-top: 16px; }
  h2 { color: #7c2d12; margin-bottom: 4px; }
  h3 { color: #7c2d12; margin-top: 24px; }
  .hint { color: #6b5d4f; font-size: 14px; }
  .error { color: #b91c1c; }
  .notice { color: #166534; }
  .empty { color: #8a7a68; }
  input { margin-right: 8px; padding: 6px; }
  button { padding: 6px 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #d8c9b8; padding: 6px 10px; text-align: left; }
  th { background: #f3eadf; }
  .remain { color: #b91c1c; font-weight: bold; }
  .ok { color: #166534; font-weight: bold; }
</style>
