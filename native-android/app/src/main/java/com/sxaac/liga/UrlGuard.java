package com.sxaac.liga;

import java.net.URI;
import java.net.URISyntaxException;
import java.net.URLDecoder;
import java.io.UnsupportedEncodingException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/** Pure Java policy shared by top-level navigation, browser links and sharing. */
public final class UrlGuard {
    public static final String HOME = "https://liga.sx-aac.com/";
    private static final String HOST = "liga.sx-aac.com";
    private static final Pattern CONTROL = Pattern.compile("[\\x00-\\x1f\\x7f]");
    private static final Pattern EMAIL = Pattern.compile("[^\\s<>@]+@[^\\s<>@]+");
    private static final Pattern TELEPHONE = Pattern.compile("\\+?[0-9(). *#-]+(?:;[a-z][a-z0-9-]*=[^;\\s]+)*", Pattern.CASE_INSENSITIVE);

    private UrlGuard() { }

    private static URI parse(String candidate) {
        if (candidate == null || candidate.isEmpty() || CONTROL.matcher(candidate).find()) return null;
        try {
            URI parsed = new URI(candidate);
            if (!parsed.isAbsolute() || parsed.getRawUserInfo() != null) return null;
            return parsed;
        } catch (URISyntaxException ignored) {
            return null;
        }
    }

    private static boolean isWeb(URI uri) {
        String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
        return (scheme.equals("https") || scheme.equals("http"))
            && uri.getHost() != null && !uri.getHost().isEmpty()
            && (uri.getPort() == -1 || (uri.getPort() > 0 && uri.getPort() <= 65535));
    }

    public static boolean isInternal(String candidate) {
        if ("about:blank".equals(candidate)) return true;
        URI uri = parse(candidate);
        return uri != null && isWeb(uri)
            && "https".equalsIgnoreCase(uri.getScheme())
            && HOST.equalsIgnoreCase(uri.getHost())
            && (uri.getPort() == -1 || uri.getPort() == 443);
    }

    public static boolean isExternalAllowed(String candidate) {
        URI uri = parse(candidate);
        if (uri == null) return false;
        if (isWeb(uri)) return true;
        String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
        if (uri.getRawAuthority() != null || uri.getRawFragment() != null) return false;
        try {
            String payload = uri.getRawSchemeSpecificPart();
            if (payload == null || payload.startsWith("//")) return false;
            if (scheme.equals("mailto")) return hasRecipients(payload);
            if (scheme.equals("tel")) {
                if (payload.indexOf('?') >= 0) return false;
                String telephone = decode(payload);
                return !CONTROL.matcher(telephone).find()
                    && TELEPHONE.matcher(telephone).matches()
                    && telephone.split(";", 2)[0].matches(".*[0-9].*");
            }
        } catch (IllegalArgumentException ignored) {
            // Malformed percent encoding is never forwarded to another app.
        }
        return false;
    }

    private static String decode(String value) {
        // '+' is part of a mailbox or international telephone number.
        try {
            return URLDecoder.decode(value.replace("+", "%2B"), "UTF-8");
        } catch (UnsupportedEncodingException impossible) {
            throw new IllegalStateException("UTF-8 is required by Android", impossible);
        }
    }

    private static boolean hasRecipients(String payload) {
        String[] parts = payload.split("\\?", 2);
        List<String> recipients = new ArrayList<>();
        recipients.add(decode(parts[0]));
        if (parts.length == 2) {
            for (String entry : parts[1].split("&")) {
                int separator = entry.indexOf('=');
                if (separator < 0) continue;
                String key = decode(entry.substring(0, separator)).toLowerCase(Locale.ROOT);
                if (key.equals("to") || key.equals("cc") || key.equals("bcc")) {
                    recipients.add(decode(entry.substring(separator + 1)));
                }
            }
        }
        boolean found = false;
        for (String group : recipients) {
            if (group.isEmpty()) continue;
            for (String recipient : group.split(",", -1)) {
                String address = recipient.trim();
                if (CONTROL.matcher(recipient).find() || hasWhitespace(address) || !EMAIL.matcher(address).matches()) return false;
                found = true;
            }
        }
        return found;
    }

    private static boolean hasWhitespace(String value) {
        // Android's regex engine rejects Java's UNICODE_CHARACTER_CLASS flag.
        // Explicit character checks keep Unicode-space behavior portable.
        for (int i = 0; i < value.length(); i++) {
            char character = value.charAt(i);
            if (Character.isWhitespace(character) || Character.isSpaceChar(character)) return true;
        }
        return false;
    }

    public static boolean isPgn(String candidate) {
        URI uri = parse(candidate);
        return uri != null && isInternal(candidate) && uri.getRawPath() != null
            && uri.getRawPath().matches("/games/[0-9]+/pgn/?");
    }

    public static boolean samePage(String first, String second) {
        URI a = parse(first);
        URI b = parse(second);
        if (a == null || b == null) return false;
        try {
            // Keep escaped delimiters escaped: %26 in a query is not an '&'.
            String rawA = a.toString();
            String rawB = b.toString();
            int fragmentA = rawA.indexOf('#');
            int fragmentB = rawB.indexOf('#');
            return new URI(fragmentA >= 0 ? rawA.substring(0, fragmentA) : rawA)
                .equals(new URI(fragmentB >= 0 ? rawB.substring(0, fragmentB) : rawB));
        } catch (URISyntaxException ignored) {
            return false;
        }
    }
}
