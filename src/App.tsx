import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  BackHandler,
  Image,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import WebView from 'react-native-webview';
import { isAllowedExternalUrl, isInternalUrl, isPgnDownloadUrl, WEBSITE_URL } from './urls';

const BRAND_BLACK = '#151515';
const BRAND_RED = '#b92031';
const LOGO = require('../assets/icon.png');

const COPY = {
  pt: {
    subtitle: 'Xadrez académico',
    back: 'Voltar',
    home: 'Início',
    refresh: 'Atualizar',
    stop: 'Parar',
    share: 'Partilhar',
    language: 'Mudar os controlos da aplicação para inglês',
    loading: 'A abrir a Liga…',
    loadingBody: 'Resultados, partidas e classificações.',
    networkHeading: 'Não foi possível ligar à Liga',
    networkBody: 'Verifica a ligação à Internet e tenta novamente. É necessária uma ligação para consultar a Liga.',
    httpHeading: 'Esta página está indisponível',
    httpBody: 'O site não conseguiu apresentar esta página. Tenta novamente ou regressa ao início.',
    stoppedHeading: 'Carregamento interrompido',
    stoppedBody: 'Podes tentar novamente quando quiseres.',
    retry: 'Tentar novamente',
    browser: 'Abrir no navegador',
    linkHeading: 'Não foi possível abrir o link',
    linkBody: 'Não foi encontrada uma aplicação para abrir este endereço.',
    shareHeading: 'Não foi possível partilhar',
    shareBody: 'Tenta partilhar esta página novamente.',
    pageError: 'Erro HTTP',
  },
  en: {
    subtitle: 'Academic chess',
    back: 'Back',
    home: 'Home',
    refresh: 'Refresh',
    stop: 'Stop',
    share: 'Share',
    language: 'Switch the app controls to Portuguese',
    loading: 'Opening the League…',
    loadingBody: 'Results, games and standings.',
    networkHeading: 'Unable to connect to the League',
    networkBody: 'Check your internet connection and try again. An internet connection is required to view the League.',
    httpHeading: 'This page is unavailable',
    httpBody: 'The website could not display this page. Try again or return home.',
    stoppedHeading: 'Loading stopped',
    stoppedBody: 'You can try again whenever you are ready.',
    retry: 'Try again',
    browser: 'Open in browser',
    linkHeading: 'Unable to open the link',
    linkBody: 'No application was found to open this address.',
    shareHeading: 'Unable to share',
    shareBody: 'Try sharing this page again.',
    pageError: 'HTTP error',
  },
};

type Failure = { kind: 'network' | 'http' | 'stopped'; statusCode?: number };

// Ignore a stale error if another top-level navigation has already started.
function samePage(first: string, second: string): boolean {
  try {
    const firstUrl = new URL(first);
    const secondUrl = new URL(second);
    firstUrl.hash = '';
    secondUrl.hash = '';
    return firstUrl.href === secondUrl.href;
  } catch {
    return false;
  }
}

function ToolbarButton({
  label,
  symbol,
  disabled = false,
  onPress,
}: {
  label: string;
  symbol: string;
  disabled?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.toolbarButton, pressed && styles.pressed, disabled && styles.disabled]}
    >
      <Text accessible={false} style={styles.toolbarSymbol}>{symbol}</Text>
      <Text accessible={false} style={styles.toolbarLabel} maxFontSizeMultiplier={1.35}>{label}</Text>
    </Pressable>
  );
}

function AppContent() {
  const webviewRef = useRef<WebView>(null);
  const currentUrl = useRef(WEBSITE_URL);
  const pageTitle = useRef('Liga SX-AAC');
  const mainPageUrl = useRef(WEBSITE_URL);
  const failureRef = useRef<Failure | null>(null);
  const stopped = useRef(false);
  const [language, setLanguage] = useState<'pt' | 'en'>('pt');
  const [canGoBack, setCanGoBack] = useState(false);
  const [loading, setLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [progress, setProgress] = useState(0);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [webviewKey, setWebviewKey] = useState(0);
  const copy = COPY[language];

  const beginLoading = useCallback(() => {
    stopped.current = false;
    failureRef.current = null;
    setFailure(null);
    setProgress(0);
    setLoading(true);
  }, []);

  const showFailure = useCallback((nextFailure: Failure) => {
    failureRef.current = nextFailure;
    setFailure(nextFailure);
    setLoading(false);
    setHasLoaded(false);
  }, []);

  const openOutside = useCallback((url: string) => {
    if (!isAllowedExternalUrl(url)) {
      Alert.alert(copy.linkHeading, copy.linkBody);
      return;
    }
    Linking.openURL(url).catch(() => Alert.alert(copy.linkHeading, copy.linkBody));
  }, [copy]);

  const goBack = useCallback(() => {
    if (!canGoBack) return;
    beginLoading();
    webviewRef.current?.goBack();
  }, [beginLoading, canGoBack]);

  useEffect(() => {
    if (Platform.OS !== 'android') return;
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (!canGoBack) return false;
      goBack();
      return true;
    });
    return () => subscription.remove();
  }, [canGoBack, goBack]);

  const retry = useCallback(() => {
    beginLoading();
    webviewRef.current?.reload();
  }, [beginLoading]);

  const goHome = useCallback(() => {
    const needsReset = failureRef.current !== null || !hasLoaded;
    beginLoading();
    if (needsReset) {
      // Recover even when the document cannot execute JavaScript. Cookies and
      // website storage remain in the normal persistent WebView data store.
      setCanGoBack(false);
      setHasLoaded(false);
      currentUrl.current = WEBSITE_URL;
      mainPageUrl.current = WEBSITE_URL;
      pageTitle.current = 'Liga SX-AAC';
      setWebviewKey((key) => key + 1);
    } else {
      webviewRef.current?.injectJavaScript(`window.location.assign(${JSON.stringify(WEBSITE_URL)}); true;`);
    }
  }, [beginLoading, hasLoaded]);

  const refreshOrStop = useCallback(() => {
    if (!loading) {
      retry();
      return;
    }
    stopped.current = true;
    webviewRef.current?.stopLoading();
    setLoading(false);
    if (!hasLoaded) showFailure({ kind: 'stopped' });
  }, [hasLoaded, loading, retry, showFailure]);

  const sharePage = useCallback(async () => {
    const url = isInternalUrl(currentUrl.current) && currentUrl.current !== 'about:blank'
      ? currentUrl.current
      : WEBSITE_URL;
    try {
      await Share.share(Platform.OS === 'ios'
        ? { title: pageTitle.current, url }
        : { title: pageTitle.current, message: `${pageTitle.current}\n${url}` });
    } catch {
      Alert.alert(copy.shareHeading, copy.shareBody);
    }
  }, [copy]);

  const errorHeading = failure?.kind === 'http' ? copy.httpHeading
    : failure?.kind === 'stopped' ? copy.stoppedHeading : copy.networkHeading;
  const errorBody = failure?.kind === 'http' ? copy.httpBody
    : failure?.kind === 'stopped' ? copy.stoppedBody : copy.networkBody;

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <StatusBar style="dark" />
      <View style={styles.header}>
        <Image source={LOGO} style={styles.headerLogo} resizeMode="contain" accessible={false} />
        <View style={styles.brand}>
          <Text style={styles.brandName} maxFontSizeMultiplier={1.4}>LIGA SX-AAC</Text>
          <Text style={styles.brandSubtitle} maxFontSizeMultiplier={1.3}>{copy.subtitle}</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={copy.language}
          onPress={() => setLanguage((value) => value === 'pt' ? 'en' : 'pt')}
          style={({ pressed }) => [styles.languageButton, pressed && styles.pressed]}
        >
          <Text style={styles.languageText}>{language.toUpperCase()} / {language === 'pt' ? 'EN' : 'PT'}</Text>
        </Pressable>
      </View>
      <View style={styles.webviewArea}>
        <WebView
          key={webviewKey}
          ref={webviewRef}
          source={{ uri: WEBSITE_URL }}
          style={styles.webview}
          // Every URL must reach our guard. WebView otherwise launches URLs
          // outside its whitelist directly, bypassing the scheme checks below.
          originWhitelist={['*']}
          mixedContentMode="never"
          javaScriptEnabled
          domStorageEnabled
          sharedCookiesEnabled
          thirdPartyCookiesEnabled={false}
          setSupportMultipleWindows={false}
          allowsBackForwardNavigationGestures
          allowsInlineMediaPlayback
          cacheEnabled
          onNavigationStateChange={(navigation) => {
            setCanGoBack(navigation.canGoBack);
            if (isInternalUrl(navigation.url) && navigation.url !== 'about:blank') {
              currentUrl.current = navigation.url;
              mainPageUrl.current = navigation.url;
              pageTitle.current = navigation.title || 'Liga SX-AAC';
            }
          }}
          onShouldStartLoadWithRequest={(request) => {
            if (request.isTopFrame === false) return true;
            if (isPgnDownloadUrl(request.url)) {
              openOutside(request.url);
              return false;
            }
            if (isInternalUrl(request.url)) return true;
            openOutside(request.url);
            return false;
          }}
          onLoadStart={({ nativeEvent }) => {
            if (isInternalUrl(nativeEvent.url) && nativeEvent.url !== 'about:blank') {
              mainPageUrl.current = nativeEvent.url;
              currentUrl.current = nativeEvent.url;
            }
            beginLoading();
          }}
          onLoadProgress={({ nativeEvent }) => {
            if (!stopped.current) setProgress(nativeEvent.progress);
          }}
          onLoadEnd={() => {
            setLoading(false);
            if (!failureRef.current && !stopped.current) setHasLoaded(true);
          }}
          onError={(event) => {
            const { nativeEvent } = event;
            if (stopped.current || (nativeEvent.url && !samePage(nativeEvent.url, mainPageUrl.current))) {
              event.preventDefault();
              return;
            }
            showFailure({ kind: 'network' });
          }}
          onHttpError={({ nativeEvent }) => {
            // Keep authentication and form-validation responses under the
            // website's control; replace missing pages and server failures.
            if ((nativeEvent.statusCode >= 500 || nativeEvent.statusCode === 404)
              && samePage(nativeEvent.url, mainPageUrl.current)) {
              showFailure({ kind: 'http', statusCode: nativeEvent.statusCode });
            }
          }}
        />
        {loading && !failure && (
          <View style={styles.progressTrack} pointerEvents="none">
            <View style={[styles.progressFill, { width: `${Math.max(8, Math.round(progress * 100))}%` }]} />
          </View>
        )}
        {!hasLoaded && loading && !failure && (
          <View style={styles.loadingOverlay} pointerEvents="none">
            <Image source={LOGO} style={styles.loadingLogo} resizeMode="contain" accessible={false} />
            <ActivityIndicator size="small" color={BRAND_RED} />
            <Text style={styles.loadingHeading} accessibilityLiveRegion="polite">{copy.loading}</Text>
            <Text style={styles.loadingBody}>{copy.loadingBody}</Text>
          </View>
        )}
        {failure && (
          <ScrollView style={styles.errorOverlay} contentContainerStyle={styles.errorContent}>
            <Image source={LOGO} style={styles.errorLogo} resizeMode="contain" accessible={false} />
            <Text style={styles.errorHeading} accessibilityRole="header" accessibilityLiveRegion="polite">{errorHeading}</Text>
            <Text style={styles.errorBody}>{errorBody}</Text>
            {failure.statusCode && <Text style={styles.errorCode}>{copy.pageError} {failure.statusCode}</Text>}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={copy.retry}
              style={({ pressed }) => [styles.retryButton, pressed && styles.retryPressed]}
              onPress={retry}
            >
              <Text style={styles.retryText}>{copy.retry}</Text>
            </Pressable>
            <Pressable
              accessibilityRole="link"
              accessibilityLabel={copy.browser}
              style={({ pressed }) => [styles.browserButton, pressed && styles.pressed]}
              onPress={() => openOutside(currentUrl.current)}
            >
              <Text style={styles.browserText}>{copy.browser}</Text>
            </Pressable>
          </ScrollView>
        )}
      </View>
      <View style={styles.toolbar}>
        <ToolbarButton label={copy.back} symbol="‹" disabled={!canGoBack} onPress={goBack} />
        <ToolbarButton label={copy.home} symbol="⌂" onPress={goHome} />
        <ToolbarButton label={loading ? copy.stop : copy.refresh} symbol={loading ? '×' : '↻'} onPress={refreshOrStop} />
        <ToolbarButton label={copy.share} symbol="↑" onPress={sharePage} />
      </View>
    </SafeAreaView>
  );
}

export default function App() {
  return <SafeAreaProvider><AppContent /></SafeAreaProvider>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#ffffff' },
  header: {
    flexDirection: 'row', alignItems: 'center', minHeight: 62,
    paddingHorizontal: 16, paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#e3e3e3',
  },
  headerLogo: { width: 38, height: 38, marginRight: 9 },
  brand: { flex: 1 },
  brandName: { color: BRAND_BLACK, fontSize: 16, fontWeight: '800', letterSpacing: 0.4 },
  brandSubtitle: { color: '#737373', fontSize: 11, marginTop: 3 },
  languageButton: { minWidth: 58, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 9 },
  languageText: { color: BRAND_RED, fontSize: 11, fontWeight: '700' },
  webviewArea: { flex: 1, backgroundColor: '#ffffff' },
  webview: { flex: 1, backgroundColor: '#ffffff' },
  progressTrack: {
    position: 'absolute', top: 0, left: 0, right: 0,
    height: 3, backgroundColor: '#f5e5e8', zIndex: 15,
  },
  progressFill: { height: 3, backgroundColor: BRAND_RED },
  loadingOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#ffffff',
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 28,
  },
  loadingLogo: { width: 104, height: 104, marginBottom: 24 },
  loadingHeading: { color: BRAND_BLACK, fontSize: 17, fontWeight: '700', marginTop: 16, textAlign: 'center' },
  loadingBody: { color: '#737373', fontSize: 13, lineHeight: 20, marginTop: 7, textAlign: 'center' },
  errorOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#ffffff',
  },
  errorContent: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 30, paddingVertical: 24 },
  errorLogo: { width: 80, height: 80, marginBottom: 22 },
  errorHeading: { color: BRAND_BLACK, fontSize: 22, fontWeight: '800', textAlign: 'center' },
  errorBody: { color: '#666666', fontSize: 15, lineHeight: 23, textAlign: 'center', marginTop: 12, marginBottom: 20 },
  errorCode: { color: '#777777', fontSize: 12, marginBottom: 20 },
  retryButton: {
    backgroundColor: BRAND_RED, paddingHorizontal: 26, paddingVertical: 15,
    borderRadius: 12, minWidth: 200, minHeight: 48, alignItems: 'center', justifyContent: 'center',
  },
  retryPressed: { backgroundColor: '#941927' },
  retryText: { color: '#ffffff', fontWeight: '700', fontSize: 15 },
  browserButton: { marginTop: 12, minHeight: 44, paddingHorizontal: 16, justifyContent: 'center', borderRadius: 9 },
  browserText: { color: '#555555', fontWeight: '600', fontSize: 14 },
  toolbar: {
    flexDirection: 'row', paddingHorizontal: 8, paddingTop: 3, paddingBottom: 3,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#e3e3e3', backgroundColor: '#ffffff',
  },
  toolbarButton: { flex: 1, minHeight: 53, alignItems: 'center', justifyContent: 'center', borderRadius: 9 },
  toolbarSymbol: { color: BRAND_BLACK, fontSize: 27, lineHeight: 30, fontWeight: '500' },
  toolbarLabel: { color: '#555555', fontSize: 10, lineHeight: 16, fontWeight: '600' },
  disabled: { opacity: 0.28 },
  pressed: { backgroundColor: '#f1f1f1' },
});
