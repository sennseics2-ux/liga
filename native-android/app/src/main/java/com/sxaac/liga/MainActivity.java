package com.sxaac.liga;

import android.app.Activity;
import android.app.AlertDialog;
import android.annotation.SuppressLint;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;

import java.io.ByteArrayInputStream;
import java.util.Collections;
import java.util.Locale;

/** A framework-only shell: the website remains responsible for accounts and chess. */
public final class MainActivity extends Activity {
    private static final int RED = Color.rgb(185, 32, 49);
    private static final int BLACK = Color.rgb(21, 21, 21);
    private static final int GREY = Color.rgb(105, 105, 105);
    private static final int FILE_REQUEST = 7001;
    private static final String NETWORK = "network";
    private static final String HTTP = "http";
    private static final String STOPPED = "stopped";

    private WebView web;
    private LinearLayout root;
    private FrameLayout browserArea;
    private ProgressBar progress;
    private View loadingOverlay;
    private ScrollView errorOverlay;
    private TextView subtitle;
    private Button languageButton;
    private ActionView backButton;
    private ActionView homeButton;
    private ActionView refreshButton;
    private ActionView shareButton;
    private ValueCallback<Uri[]> fileCallback;
    private Context languageContext;
    private String language = "pt";
    private String currentUrl = UrlGuard.HOME;
    private String mainPageUrl = UrlGuard.HOME;
    private String pageTitle = "Liga SX-AAC";
    private String failure;
    private int statusCode;
    private boolean loading = true;
    private boolean hasLoaded;
    private boolean stopped;
    private OnBackInvokedCallback backCallback;
    private boolean backCallbackRegistered;

    @Override public void onCreate(Bundle state) {
        setTheme(R.style.LigaTheme);
        super.onCreate(state);
        language = getPreferences(MODE_PRIVATE).getString("language", "pt");
        updateLanguageContext();
        configureWindow();
        buildInterface();
        configureWebView();
        if (state != null && state.getBundle("web") != null && web.restoreState(state.getBundle("web")) != null) {
            String savedUrl = state.getString("url", UrlGuard.HOME);
            currentUrl = UrlGuard.isInternal(savedUrl) ? savedUrl : UrlGuard.HOME;
            mainPageUrl = currentUrl;
            hasLoaded = state.getBoolean("hasLoaded", false);
            pageTitle = state.getString("title", "Liga SX-AAC");
            loading = !hasLoaded;
            refreshInterface();
        } else {
            loadUrl(UrlGuard.HOME);
        }
    }

    private void configureWindow() {
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(Color.TRANSPARENT);
        int flags = View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
        if (Build.VERSION.SDK_INT >= 26) flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        getWindow().getDecorView().setSystemUiVisibility(flags);
        if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(false);
        if (Build.VERSION.SDK_INT >= 29) {
            getWindow().setStatusBarContrastEnforced(false);
            getWindow().setNavigationBarContrastEnforced(false);
        }
    }

    private void buildInterface() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        setContentView(root);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets system = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                Insets keyboard = insets.getInsets(WindowInsets.Type.ime());
                view.setPadding(system.left, system.top, system.right, Math.max(system.bottom, keyboard.bottom));
            } else {
                view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
        root.requestApplyInsets();

        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(12), dp(6), dp(12), dp(6));
        header.setMinimumHeight(dp(64));
        root.addView(header, new LinearLayout.LayoutParams(-1, -2));
        ImageView logo = logo(44);
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(dp(44), dp(44));
        logoParams.setMarginEnd(dp(8));
        header.addView(logo, logoParams);
        LinearLayout brand = new LinearLayout(this);
        brand.setOrientation(LinearLayout.VERTICAL);
        header.addView(brand, new LinearLayout.LayoutParams(0, -2, 1));
        TextView name = text("LIGA SX-AAC", 15, BLACK, true);
        name.setLetterSpacing(0.025f);
        if (Build.VERSION.SDK_INT >= 28) name.setAccessibilityHeading(true);
        brand.addView(name);
        subtitle = text(t(R.string.subtitle), 11, GREY, false);
        brand.addView(subtitle);
        languageButton = new Button(this);
        languageButton.setTextSize(11);
        languageButton.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        languageButton.setTextColor(RED);
        languageButton.setAllCaps(false);
        languageButton.setMinWidth(dp(62));
        languageButton.setMinimumWidth(dp(62));
        languageButton.setMinHeight(dp(48));
        languageButton.setMinimumHeight(dp(48));
        languageButton.setPadding(dp(6), 0, dp(6), 0);
        languageButton.setBackground(buttonBackground(Color.WHITE, Color.rgb(241, 241, 241), 9));
        languageButton.setOnClickListener(view -> {
            language = language.equals("pt") ? "en" : "pt";
            getPreferences(MODE_PRIVATE).edit().putString("language", language).apply();
            updateLanguageContext();
            rebuildOverlays();
            refreshInterface();
        });
        header.addView(languageButton, new LinearLayout.LayoutParams(-2, -2));
        root.addView(divider(), new LinearLayout.LayoutParams(-1, dp(1)));

        browserArea = new FrameLayout(this);
        browserArea.setBackgroundColor(Color.WHITE);
        root.addView(browserArea, new LinearLayout.LayoutParams(-1, 0, 1));
        web = new WebView(this);
        web.setBackgroundColor(Color.WHITE);
        web.setId(View.generateViewId());
        browserArea.addView(web, new FrameLayout.LayoutParams(-1, -1));
        rebuildOverlays();
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        progress.setProgressTintList(ColorStateList.valueOf(RED));
        progress.setProgressBackgroundTintList(ColorStateList.valueOf(Color.rgb(245, 229, 232)));
        FrameLayout.LayoutParams progressParams = new FrameLayout.LayoutParams(-1, dp(3), Gravity.TOP);
        browserArea.addView(progress, progressParams);

        root.addView(divider(), new LinearLayout.LayoutParams(-1, dp(1)));
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setPadding(dp(6), dp(3), dp(6), dp(3));
        root.addView(toolbar, new LinearLayout.LayoutParams(-1, -2));
        backButton = toolbarButton(toolbar, R.drawable.ic_back, R.string.back, view -> goBack());
        homeButton = toolbarButton(toolbar, R.drawable.ic_home, R.string.home, view -> loadUrl(UrlGuard.HOME));
        refreshButton = toolbarButton(toolbar, R.drawable.ic_stop, R.string.stop, view -> refreshOrStop());
        shareButton = toolbarButton(toolbar, R.drawable.ic_share, R.string.share, view -> sharePage());
        refreshInterface();
    }

    private void configureWebView() {
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setAllowFileAccess(false);
        // Document-picker uploads need content URI access. Top-level content://
        // navigation still fails the URL policy below; no local file access.
        settings.setAllowContentAccess(true);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        if (Build.VERSION.SDK_INT >= 26) settings.setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                // POST forms do not always call shouldOverrideUrlLoading. Stop
                // a foreign top-level request before it can carry form data.
                // This callback runs off the UI thread and never starts intents.
                if (request.isForMainFrame() && !UrlGuard.isInternal(request.getUrl().toString())) {
                    return new WebResourceResponse("text/plain", "UTF-8", 403, "Blocked navigation",
                        Collections.emptyMap(), new ByteArrayInputStream(new byte[0]));
                }
                return null;
            }

            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (!request.isForMainFrame()) {
                    // Subframes may use web documents, but never native app schemes.
                    String scheme = request.getUrl().getScheme();
                    return !("https".equalsIgnoreCase(scheme) || "http".equalsIgnoreCase(scheme)
                        || "about:blank".equals(url));
                }
                return handleNavigation(url);
            }

            @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleNavigation(url);
            }

            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                if (!UrlGuard.isInternal(url)) {
                    view.stopLoading();
                    openOutside(url);
                    return;
                }
                if (!"about:blank".equals(url)) {
                    mainPageUrl = url;
                    currentUrl = url;
                }
                beginLoading();
            }

            @Override public void onPageFinished(WebView view, String url) {
                if (!UrlGuard.samePage(url, mainPageUrl) || stopped) return;
                loading = false;
                if (failure == null) hasLoaded = true;
                CookieManager.getInstance().flush();
                refreshInterface();
            }

            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && !stopped
                    && UrlGuard.samePage(request.getUrl().toString(), mainPageUrl)) showFailure(NETWORK, 0);
            }

            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                int code = response.getStatusCode();
                if (request.isForMainFrame() && !stopped && (code == 404 || code >= 500)
                    && UrlGuard.samePage(request.getUrl().toString(), mainPageUrl)) showFailure(HTTP, code);
            }

            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                if (!stopped && UrlGuard.samePage(error.getUrl(), mainPageUrl)) showFailure(NETWORK, 0);
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int value) {
                if (loading && !stopped) progress.setProgress(Math.max(8, value));
            }

            @Override public void onReceivedTitle(WebView view, String title) {
                if (title != null && !title.trim().isEmpty() && UrlGuard.isInternal(view.getUrl())) pageTitle = title;
            }

            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    Intent choose = params.createIntent();
                    choose.addCategory(Intent.CATEGORY_OPENABLE);
                    choose.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                    startActivityForResult(Intent.createChooser(choose, t(R.string.select_file)), FILE_REQUEST);
                } catch (ActivityNotFoundException | SecurityException exception) {
                    fileCallback.onReceiveValue(null);
                    fileCallback = null;
                    showLinkError();
                }
                return true;
            }
        });
        web.setDownloadListener((url, userAgent, disposition, mime, length) -> openOutside(url));
    }

    private boolean handleNavigation(String url) {
        if (UrlGuard.isPgn(url)) {
            openOutside(url);
            return true;
        }
        if (UrlGuard.isInternal(url)) return false;
        openOutside(url);
        return true;
    }

    private void beginLoading() {
        stopped = false;
        failure = null;
        statusCode = 0;
        loading = true;
        progress.setProgress(8);
        refreshInterface();
    }

    private void loadUrl(String url) {
        if (!UrlGuard.isInternal(url) || "about:blank".equals(url)) return;
        mainPageUrl = url;
        currentUrl = url;
        beginLoading();
        web.loadUrl(url);
    }

    private void retry() {
        // Explicitly load the trusted URL so recovery also works after a failed document.
        loadUrl(currentUrl);
    }

    private void goBack() {
        if (!web.canGoBack()) return;
        beginLoading();
        web.goBack();
    }

    // Android 7–12 still dispatch hardware Back here. API33+ history uses the
    // registered OnBackInvokedCallback, and its default exit stays system-owned.
    @SuppressLint("GestureBackNavigation")
    @Override public void onBackPressed() {
        if (web.canGoBack()) goBack();
        else super.onBackPressed();
    }

    private void refreshOrStop() {
        if (!loading) {
            retry();
            return;
        }
        stopped = true;
        web.stopLoading();
        loading = false;
        if (!hasLoaded) showFailure(STOPPED, 0);
        else refreshInterface();
    }

    private void showFailure(String kind, int code) {
        failure = kind;
        statusCode = code;
        loading = false;
        hasLoaded = false;
        rebuildOverlays();
        refreshInterface();
    }

    private void openOutside(String url) {
        if (!UrlGuard.isExternalAllowed(url)) {
            showLinkError();
            return;
        }
        Uri uri = Uri.parse(url);
        String action = "tel".equalsIgnoreCase(uri.getScheme()) ? Intent.ACTION_DIAL
            : "mailto".equalsIgnoreCase(uri.getScheme()) ? Intent.ACTION_SENDTO : Intent.ACTION_VIEW;
        try {
            startActivity(new Intent(action, uri));
        } catch (ActivityNotFoundException | SecurityException exception) {
            showLinkError();
        }
    }

    private void showLinkError() {
        new AlertDialog.Builder(this).setTitle(t(R.string.link_heading)).setMessage(t(R.string.link_body))
            .setPositiveButton(android.R.string.ok, null).show();
    }

    private void sharePage() {
        String url = UrlGuard.isInternal(currentUrl) && !"about:blank".equals(currentUrl) ? currentUrl : UrlGuard.HOME;
        Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain")
            .putExtra(Intent.EXTRA_SUBJECT, pageTitle).putExtra(Intent.EXTRA_TEXT, pageTitle + "\n" + url);
        try {
            startActivity(Intent.createChooser(share, t(R.string.share)));
        } catch (ActivityNotFoundException | SecurityException exception) {
            new AlertDialog.Builder(this).setTitle(t(R.string.share_heading)).setMessage(t(R.string.share_body))
                .setPositiveButton(android.R.string.ok, null).show();
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_REQUEST && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
        }
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        Bundle webState = new Bundle();
        web.saveState(webState);
        state.putBundle("web", webState);
        state.putString("url", currentUrl);
        state.putString("title", pageTitle);
        state.putBoolean("hasLoaded", hasLoaded);
        super.onSaveInstanceState(state);
    }

    @Override protected void onPause() {
        web.onPause();
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
    }

    @Override protected void onDestroy() {
        if (Build.VERSION.SDK_INT >= 33 && backCallbackRegistered) {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(backCallback);
            backCallbackRegistered = false;
        }
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        if (web != null) {
            browserArea.removeView(web);
            web.stopLoading();
            web.destroy();
        }
        super.onDestroy();
    }

    private void updateLanguageContext() {
        Configuration configuration = new Configuration(getResources().getConfiguration());
        configuration.setLocale(new Locale(language.equals("en") ? "en" : "pt"));
        languageContext = createConfigurationContext(configuration);
    }

    private String t(int resource) { return languageContext.getString(resource); }

    private void refreshInterface() {
        if (backButton == null) return;
        subtitle.setText(t(R.string.subtitle));
        languageButton.setText(language.equals("pt") ? "PT / EN" : "EN / PT");
        languageButton.setContentDescription(t(R.string.language_switch));
        backButton.label(t(R.string.back));
        backButton.setEnabled(web.canGoBack());
        backButton.setAlpha(web.canGoBack() ? 1f : 0.28f);
        updateBackHandler();
        homeButton.label(t(R.string.home));
        refreshButton.label(t(loading ? R.string.stop : R.string.refresh));
        refreshButton.icon(loading ? R.drawable.ic_stop : R.drawable.ic_refresh);
        shareButton.label(t(R.string.share));
        boolean errorVisible = failure != null;
        loadingOverlay.setVisibility(!hasLoaded && loading && !errorVisible ? View.VISIBLE : View.GONE);
        errorOverlay.setVisibility(errorVisible ? View.VISIBLE : View.GONE);
        progress.setVisibility(loading && !errorVisible ? View.VISIBLE : View.GONE);
        web.setImportantForAccessibility(errorVisible || (!hasLoaded && loading)
            ? View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS : View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
    }

    private void updateBackHandler() {
        if (Build.VERSION.SDK_INT < 33) return;
        if (web.canGoBack() && !backCallbackRegistered) {
            if (backCallback == null) backCallback = this::goBack;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, backCallback);
            backCallbackRegistered = true;
        } else if (!web.canGoBack() && backCallbackRegistered) {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(backCallback);
            backCallbackRegistered = false;
        }
    }

    private void rebuildOverlays() {
        if (loadingOverlay != null) browserArea.removeView(loadingOverlay);
        if (errorOverlay != null) browserArea.removeView(errorOverlay);
        LinearLayout loadingContent = new LinearLayout(this);
        loadingContent.setOrientation(LinearLayout.VERTICAL);
        loadingContent.setGravity(Gravity.CENTER);
        loadingContent.setPadding(dp(28), dp(24), dp(28), dp(24));
        loadingContent.setBackgroundColor(Color.WHITE);
        loadingContent.addView(logo(104), centeredParams(104, 104, 0, 20));
        ProgressBar spinner = new ProgressBar(this);
        spinner.setIndeterminateTintList(ColorStateList.valueOf(RED));
        loadingContent.addView(spinner, centeredParams(24, 24, 0, 16));
        TextView loadingHeading = centeredText(t(R.string.loading), 17, BLACK, true);
        loadingHeading.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        loadingContent.addView(loadingHeading);
        TextView loadingBody = centeredText(t(R.string.loading_body), 13, GREY, false);
        loadingBody.setPadding(0, dp(7), 0, 0);
        loadingContent.addView(loadingBody);
        loadingOverlay = loadingContent;
        browserArea.addView(loadingOverlay, new FrameLayout.LayoutParams(-1, -1));

        errorOverlay = new ScrollView(this);
        errorOverlay.setFillViewport(true);
        errorOverlay.setBackgroundColor(Color.WHITE);
        LinearLayout errorContent = new LinearLayout(this);
        errorContent.setOrientation(LinearLayout.VERTICAL);
        errorContent.setGravity(Gravity.CENTER);
        errorContent.setPadding(dp(30), dp(24), dp(30), dp(24));
        errorOverlay.addView(errorContent, new ScrollView.LayoutParams(-1, -2));
        errorContent.addView(logo(80), centeredParams(80, 80, 0, 22));
        int heading = HTTP.equals(failure) ? R.string.http_heading : STOPPED.equals(failure) ? R.string.stopped_heading : R.string.network_heading;
        int body = HTTP.equals(failure) ? R.string.http_body : STOPPED.equals(failure) ? R.string.stopped_body : R.string.network_body;
        TextView errorHeading = centeredText(t(heading), 22, BLACK, true);
        if (Build.VERSION.SDK_INT >= 28) errorHeading.setAccessibilityHeading(true);
        errorHeading.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        errorContent.addView(errorHeading);
        TextView errorBody = centeredText(t(body), 15, GREY, false);
        errorBody.setLineSpacing(dp(4), 1f);
        errorBody.setPadding(0, dp(12), 0, dp(20));
        errorContent.addView(errorBody);
        if (statusCode != 0) {
            TextView code = centeredText(languageContext.getString(R.string.page_error, statusCode), 12, GREY, false);
            code.setPadding(0, 0, 0, dp(20));
            errorContent.addView(code);
        }
        Button retry = new Button(this);
        retry.setText(t(R.string.retry));
        retry.setAllCaps(false);
        retry.setTextSize(15);
        retry.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        retry.setTextColor(Color.WHITE);
        retry.setMinHeight(dp(50));
        retry.setPadding(dp(26), dp(12), dp(26), dp(12));
        retry.setBackground(buttonBackground(RED, Color.rgb(148, 25, 39), 12));
        retry.setOnClickListener(view -> retry());
        LinearLayout.LayoutParams retryParams = new LinearLayout.LayoutParams(-2, -2);
        retryParams.gravity = Gravity.CENTER_HORIZONTAL;
        retry.setMinWidth(dp(200));
        errorContent.addView(retry, retryParams);
        Button browser = new Button(this);
        browser.setText(t(R.string.browser));
        browser.setAllCaps(false);
        browser.setTextSize(14);
        browser.setTextColor(Color.rgb(85, 85, 85));
        browser.setMinHeight(dp(48));
        browser.setPadding(dp(16), 0, dp(16), 0);
        browser.setBackground(buttonBackground(Color.WHITE, Color.rgb(241, 241, 241), 9));
        browser.setOnClickListener(view -> openOutside(currentUrl));
        LinearLayout.LayoutParams browserParams = new LinearLayout.LayoutParams(-2, -2);
        browserParams.topMargin = dp(12);
        browserParams.gravity = Gravity.CENTER_HORIZONTAL;
        errorContent.addView(browser, browserParams);
        browserArea.addView(errorOverlay, new FrameLayout.LayoutParams(-1, -1));
        if (progress != null) progress.bringToFront();
    }

    private ActionView toolbarButton(LinearLayout parent, int icon, int label, View.OnClickListener listener) {
        ActionView button = new ActionView(this);
        button.icon(icon);
        button.label(t(label));
        button.setOnClickListener(listener);
        parent.addView(button, new LinearLayout.LayoutParams(0, -2, 1));
        return button;
    }

    private ImageView logo(int size) {
        ImageView image = new ImageView(this);
        image.setImageResource(R.drawable.liga_logo);
        image.setScaleType(ImageView.ScaleType.FIT_CENTER);
        image.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        image.setMinimumWidth(dp(size));
        image.setMinimumHeight(dp(size));
        return image;
    }

    private View divider() {
        View line = new View(this);
        line.setBackgroundColor(Color.rgb(227, 227, 227));
        line.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        return line;
    }

    private TextView text(String value, int sp, int color, boolean bold) {
        TextView text = new TextView(this);
        text.setText(value);
        text.setTextSize(sp);
        text.setTextColor(color);
        if (bold) text.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return text;
    }

    private TextView centeredText(String value, int sp, int color, boolean bold) {
        TextView text = text(value, sp, color, bold);
        text.setGravity(Gravity.CENTER);
        return text;
    }

    private LinearLayout.LayoutParams centeredParams(int width, int height, int top, int bottom) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(width), dp(height));
        params.gravity = Gravity.CENTER_HORIZONTAL;
        params.topMargin = dp(top);
        params.bottomMargin = dp(bottom);
        return params;
    }

    private RippleDrawable buttonBackground(int color, int pressed, int radius) {
        GradientDrawable background = new GradientDrawable();
        background.setColor(color);
        background.setCornerRadius(dp(radius));
        GradientDrawable mask = new GradientDrawable();
        mask.setColor(Color.WHITE);
        mask.setCornerRadius(dp(radius));
        return new RippleDrawable(ColorStateList.valueOf(pressed), background, mask);
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private final class ActionView extends LinearLayout {
        private final ImageView image;
        private final TextView caption;

        ActionView(Context context) {
            super(context);
            setOrientation(LinearLayout.VERTICAL);
            setGravity(Gravity.CENTER);
            setPadding(dp(4), dp(6), dp(4), dp(5));
            setMinimumHeight(dp(58));
            setFocusable(true);
            setClickable(true);
            setBackground(buttonBackground(Color.WHITE, Color.rgb(241, 241, 241), 9));
            image = new ImageView(context);
            image.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            addView(image, new LinearLayout.LayoutParams(dp(24), dp(24)));
            caption = text("", 10, Color.rgb(85, 85, 85), true);
            caption.setGravity(Gravity.CENTER);
            caption.setPadding(0, dp(3), 0, 0);
            caption.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            addView(caption, new LinearLayout.LayoutParams(-1, -2));
        }

        void label(String value) {
            caption.setText(value);
            setContentDescription(value);
        }

        void icon(int resource) { image.setImageResource(resource); }

        @Override public CharSequence getAccessibilityClassName() { return Button.class.getName(); }
    }
}
