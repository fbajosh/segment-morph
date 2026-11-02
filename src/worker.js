// Hostname-independent static asset routing.
// Use the Cloudflare dashboard to attach the desired hostname/path to this Worker.
// The public app is mounted at /segment-morph/, and works at / on workers.dev.
const APP_PATH = '/segment-morph';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === APP_PATH) {
      url.pathname = APP_PATH + '/';
      return Response.redirect(url.toString(), 308);
    }

    if (url.pathname.startsWith(APP_PATH + '/')) {
      url.pathname = url.pathname.slice(APP_PATH.length);
    }

    return env.ASSETS.fetch(new Request(url.toString(), request));
  },
};
