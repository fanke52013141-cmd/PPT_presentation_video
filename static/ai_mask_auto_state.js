(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.createAiMaskAutoState = api.createAiMaskAutoState;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function createAiMaskAutoState(options = {}) {
    const schedule = options.schedule || setTimeout;
    const cancel = options.cancel || clearTimeout;
    const retryDelays = options.retryDelays || [1000, 3000];
    const states = new Map();

    function current(projectId) {
      if (!states.has(projectId)) {
        states.set(projectId, { status: 'idle', retries: 0, timer: null });
      }
      return states.get(projectId);
    }

    function clearTimer(state) {
      if (state.timer !== null) cancel(state.timer);
      state.timer = null;
    }

    function setStatus(projectId, status) {
      const state = current(projectId);
      clearTimer(state);
      state.status = status;
      return state;
    }

    function canStart(projectId) {
      return !['checking', 'running', 'retry_wait', 'waiting_one_click'].includes(current(projectId).status);
    }

    function begin(projectId, status = 'running') {
      setStatus(projectId, status);
    }

    function complete(projectId) {
      const state = setStatus(projectId, 'completed');
      state.retries = 0;
    }

    function fail(projectId) {
      setStatus(projectId, 'failed');
    }

    function scheduleRetry(projectId, callback) {
      const state = current(projectId);
      if (state.retries >= retryDelays.length) {
        fail(projectId);
        return null;
      }
      clearTimer(state);
      const delay = retryDelays[state.retries];
      state.retries += 1;
      state.status = 'retry_wait';
      state.timer = schedule(() => {
        state.timer = null;
        state.status = 'idle';
        callback();
      }, delay);
      return delay;
    }

    function waitForOneClick(projectId, callback, delay = 2500) {
      const state = setStatus(projectId, 'waiting_one_click');
      state.timer = schedule(() => {
        state.timer = null;
        state.status = 'idle';
        callback();
      }, delay);
    }

    function reset(projectId = null) {
      if (projectId !== null) {
        const state = states.get(projectId);
        if (state) clearTimer(state);
        states.delete(projectId);
        return;
      }
      states.forEach(clearTimer);
      states.clear();
    }

    return {
      begin,
      canStart,
      complete,
      fail,
      get: projectId => ({ ...current(projectId), timer: null }),
      reset,
      scheduleRetry,
      waitForOneClick,
    };
  }

  return { createAiMaskAutoState };
});
