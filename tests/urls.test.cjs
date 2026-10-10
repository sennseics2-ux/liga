const { test } = require('node:test');
const assert = require('node:assert/strict');

// Node 24 loads the production TypeScript with built-in type stripping.
const api = require('../src/urls.ts');

test('website URL is the actual HTTPS club domain', () => {
  assert.equal(api.WEBSITE_URL, 'https://liga.sx-aac.com/');
  assert.equal(api.WEBSITE_ORIGIN, 'https://liga.sx-aac.com');
});

test('allow only exact HTTPS origin for authenticated pages', () => {
  for (const url of [
    'https://liga.sx-aac.com',
    'https://liga.sx-aac.com/',
    'https://liga.sx-aac.com/users/pedro',
    'https://liga.sx-aac.com/teams?sort=points_desc',
    'https://liga.sx-aac.com:443/players',
    'about:blank',
  ]) assert.equal(api.isInternalUrl(url), true, url);
});

test('reject unrelated origins, credentials, and non-default ports from authenticated pages', () => {
  for (const url of [
    'http://liga.sx-aac.com',
    'https://liga.sx-aac.com.attacker.test',
    'https://notliga.sx-aac.com',
    'https://www.liga.sx-aac.com',
    'https://liga.sx-aac.com:8443',
    'https://liga.sx-aac.com:80',
    'https://evil.test/?continue=https://liga.sx-aac.com',
    'https://liga.sx-aac.com@evil.test',
    'https://u:pass@liga.sx-aac.com',
    'https://u@liga.sx-aac.com',
    'about:blank#other',
  ]) assert.equal(api.isInternalUrl(url), false, url);
});

test('malformed URLs, controls, and unsafe schemes cannot navigate or launch applications', () => {
  for (const url of [
    '',
    '/games/9',
    '//liga.sx-aac.com/',
    'https://',
    'https://%invalid/',
    'https://liga.sx-aac.com:invalid/',
    'https://li\nga.sx-aac.com/',
    'https://liga.sx-aac.com/\u0000',
    'javascript:alert(1)',
    'data:text/html,<h1>Bad</h1>',
    'file:///etc/passwd',
    'intent://anotherapp',
  ]) {
    assert.equal(api.isInternalUrl(url), false, url);
    assert.equal(api.isAllowedExternalUrl(url), false, url);
    assert.equal(api.isPgnDownloadUrl(url), false, url);
  }
});

test('external web links allow HTTP and HTTPS without embedded credentials', () => {
  for (const url of ['https://example.com', 'http://example.com', api.WEBSITE_URL])
    assert.equal(api.isAllowedExternalUrl(url), true, url);
  for (const url of ['https://u:pass@example.com', 'http://u@example.com'])
    assert.equal(api.isAllowedExternalUrl(url), false, url);
});

test('email links support recipients, address tags, and message options', () => {
  for (const url of [
    'mailto:club@example.com',
    'mailto:club+liga@example.com?subject=Resultados&body=Ol%C3%A1%0AObrigado',
    'mailto:club@example.com,other@example.com?cc=team@example.com',
    'mailto:?to=club+liga@example.com&subject=Resultados',
  ]) assert.equal(api.isAllowedExternalUrl(url), true, url);
  for (const url of [
    'mailto:',
    'mailto:?subject=Resultados',
    'mailto:invalid-address',
    'mailto:club@example.com,',
    'mailto:club%0A@example.com',
    'mailto:%0Aclub@example.com',
    'mailto:%invalid@example.com',
    'mailto://club@example.com',
  ]) assert.equal(api.isAllowedExternalUrl(url), false, url);
});

test('telephone links support formatted numbers, extensions, and local phone context', () => {
  for (const url of [
    'tel:+351239000000',
    'tel:+351-239-000-000',
    'tel:(239)%20000%20000',
    'tel:+351239000000;ext=123',
    'tel:239000000;phone-context=+351',
    'tel:*123%23',
  ]) assert.equal(api.isAllowedExternalUrl(url), true, url);
  for (const url of [
    'tel:',
    'tel:call-me',
    'tel:+++351239000000',
    'tel:+351%0A239000000',
    'tel:+351239000000;ext=%00',
    'tel:%invalid',
    'tel:+351239000000;ext=',
    'tel:+351239000000?number=other',
  ]) assert.equal(api.isAllowedExternalUrl(url), false, url);
});

test('PGN downloads support optional trailing slash, query, and fragment', () => {
  for (const url of [
    'https://liga.sx-aac.com/games/9/pgn',
    'https://liga.sx-aac.com/games/9/pgn/',
    'https://liga.sx-aac.com/games/9/pgn?download=1',
    'https://liga.sx-aac.com/games/9/pgn/?download=1#file',
  ]) assert.equal(api.isPgnDownloadUrl(url), true, url);
});

test('PGN routing cannot intercept ordinary pages or downloads from other origins', () => {
  for (const url of [
    'https://liga.sx-aac.com/games/9',
    'https://liga.sx-aac.com/games/9/pgn/extra',
    'https://liga.sx-aac.com/games/not-a-number/pgn',
    'https://evil.test/games/9/pgn',
    'http://liga.sx-aac.com/games/9/pgn',
    'https://liga.sx-aac.com:8443/games/9/pgn',
    'https://u:pass@liga.sx-aac.com/games/9/pgn',
    'about:blank',
  ]) assert.equal(api.isPgnDownloadUrl(url), false, url);
});
