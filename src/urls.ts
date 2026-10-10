export const WEBSITE_URL = 'https://liga.sx-aac.com/';
export const WEBSITE_ORIGIN = 'https://liga.sx-aac.com';

function parseUrl(candidate: string): URL | null {
  // URL parsers silently remove some control characters. Reject them before
  // deciding whether the original link may be passed to a native application.
  if (!candidate || /[\u0000-\u001f\u007f]/.test(candidate)) return null;
  try {
    const url = new URL(candidate);
    return url.username || url.password ? null : url;
  } catch {
    return null;
  }
}

/** Only the canonical HTTPS origin is allowed inside the authenticated webview. */
export function isInternalUrl(candidate: string): boolean {
  if (candidate === 'about:blank') return true;
  const url = parseUrl(candidate);
  return !!url && url.protocol === 'https:' && url.origin === WEBSITE_ORIGIN;
}

function hasEmailRecipients(url: URL): boolean {
  const recipients = [decodeURIComponent(url.pathname)];
  for (const parameter of url.search.slice(1).split('&')) {
    const separator = parameter.indexOf('=');
    if (separator < 0) continue;
    const name = decodeURIComponent(parameter.slice(0, separator)).toLowerCase();
    if (name === 'to' || name === 'cc' || name === 'bcc') {
      // A literal '+' belongs to an email address, unlike form-encoded data.
      recipients.push(decodeURIComponent(parameter.slice(separator + 1)));
    }
  }
  const addresses = recipients.filter(Boolean).flatMap((value) => value.split(','));
  return addresses.length > 0 && addresses.every((address) =>
    !/[\u0000-\u001f\u007f]/.test(address) && /^[^\s<>@]+@[^\s<>@]+$/.test(address.trim()));
}

function hasTelephoneNumber(url: URL): boolean {
  if (url.search || url.hash) return false;
  const telephone = decodeURIComponent(url.pathname);
  if (/[\u0000-\u001f\u007f]/.test(telephone)) return false;
  if (!/^\+?[0-9(). *#-]+(?:;[a-z][a-z0-9-]*=[^;\s]+)*$/i.test(telephone)) return false;
  return /\d/.test(telephone.split(';')[0]);
}

/** Only external web links or known telephone / email links can launch native apps. */
export function isAllowedExternalUrl(candidate: string): boolean {
  const url = parseUrl(candidate);
  if (!url) return false;
  try {
    if (url.protocol === 'https:' || url.protocol === 'http:') return true;
    if (url.protocol === 'mailto:') return !url.host && !url.hash && hasEmailRecipients(url);
    if (url.protocol === 'tel:') return !url.host && hasTelephoneNumber(url);
    return false;
  } catch {
    // Invalid percent encoding is rejected when decoding native-app links.
    return false;
  }
}

/** PGN files are downloaded by the phone's browser, not inside the WebView. */
export function isPgnDownloadUrl(candidate: string): boolean {
  if (!isInternalUrl(candidate)) return false;
  try {
    const url = new URL(candidate);
    return /^\/games\/\d+\/pgn\/?$/.test(url.pathname);
  } catch {
    return false;
  }
}
