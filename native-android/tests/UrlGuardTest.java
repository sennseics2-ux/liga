package com.sxaac.liga;

public final class UrlGuardTest {
    private static int assertions;

    private static void expect(boolean actual, boolean expected, String message) {
        assertions++;
        if (actual != expected) throw new AssertionError(message + ": expected " + expected + ", got " + actual);
    }

    public static void main(String[] args) {
        for (String url : new String[] {
            UrlGuard.HOME, "https://LIGA.SX-AAC.COM:443/games/9", "https://liga.sx-aac.com/?tab=games#top", "about:blank"
        }) expect(UrlGuard.isInternal(url), true, "Trusted page " + url);

        for (String url : new String[] {
            "http://liga.sx-aac.com/", "https://liga.sx-aac.com:444/", "https://evil.example/",
            "https://liga.sx-aac.com.evil.example/", "https://liga.sx-aac.com@evil.example/",
            "https://user:pass@liga.sx-aac.com/", "https://liga.sx-aac.com\n/", "https://liga.sx-aac.com\\@evil.example/",
            "javascript:alert(1)", "file:///sdcard/test", "content://private/data", "about:blank#x", "", "//liga.sx-aac.com/"
        }) expect(UrlGuard.isInternal(url), false, "Untrusted page " + url);

        for (String url : new String[] {
            "https://example.com/page", "http://example.com:8080/", "https://[::1]/",
            "mailto:liga+info@sx-aac.com", "mailto:?to=one%40example.com&cc=two%40example.com",
            "mailto:one@example.com,two@example.com?subject=League&body=Hello%0Athere",
            "tel:+351-239-000-000", "tel:239000000;ext=23"
        }) expect(UrlGuard.isExternalAllowed(url), true, "Allowed browser or native link " + url);

        for (String url : new String[] {
            "intent://evil#Intent;scheme=https;end", "javascript:alert(1)", "data:text/html,hello",
            "file:///secret", "content://private/data", "ftp://example.com/", "https://user@host/", "https://example.com\t/",
            "https:///nohost", "mailto:", "mailto:bad", "mailto:good@example.com,bad", "mailto://good@example.com",
            "mailto:good@example.com?cc=bad", "mailto:bad%0D%0ABcc:attacker@example.com", "mailto:bad%ZZ@example.com",
            "mailto:bad%20name@example.com", "mailto:bad%C2%A0name@example.com", "mailto:bad%E2%80%83name@example.com",
            "tel:", "tel:+", "tel:call-me", "tel:123?foo=bar", "tel:123#fragment", "tel:123%0A456"
        }) expect(UrlGuard.isExternalAllowed(url), false, "Rejected native link " + url);

        for (String url : new String[] {
            "https://liga.sx-aac.com/games/9/pgn", "https://liga.sx-aac.com/games/123/pgn/?download=1#file"
        }) expect(UrlGuard.isPgn(url), true, "PGN download " + url);

        for (String url : new String[] {
            "https://evil.example/games/9/pgn", "https://liga.sx-aac.com/games/not-a-number/pgn",
            "https://liga.sx-aac.com/%67ames/9/pgn", "https://liga.sx-aac.com/games/9/pgn-extra", "about:blank"
        }) expect(UrlGuard.isPgn(url), false, "Other page " + url);

        expect(UrlGuard.samePage(UrlGuard.HOME + "games?x=1#top", UrlGuard.HOME + "games?x=1#bottom"), true, "Fragments ignored");
        expect(UrlGuard.samePage(UrlGuard.HOME + "games?a=x%26b=y", UrlGuard.HOME + "games?a=x&b=y"), false, "Encoded query delimiter stays distinct");
        expect(UrlGuard.samePage(UrlGuard.HOME + "games%2F9", UrlGuard.HOME + "games/9"), false, "Encoded path delimiter stays distinct");
        expect(UrlGuard.samePage("not a url", UrlGuard.HOME), false, "Invalid pages differ");
        System.out.println("UrlGuard: " + assertions + " assertions passed");
    }
}
