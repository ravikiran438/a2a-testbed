// Copyright 2026 Ravi Kiran Kadaboina
// Licensed under the Apache License, Version 2.0.
//
// Java reference agent for the a2a-testbed subprocess runtime.
//
// Reads CLI args --agent-card, --scripts, --port; binds an HTTP server on
// 127.0.0.1; serves the AgentCard at the well-known URL and a minimal
// JSON-RPC message/send endpoint. Prints "A2A_TESTBED_READY: <url>" on
// stdout when listening. Mirrors agents/nodejs-template/index.js so the
// cross-SDK polyglot story includes Java.
//
// JDK stdlib only (com.sun.net.httpserver + java.util.regex) — no JSON
// library — so it builds into a single dependency-free jar. Real agents
// would swap to a full A2A SDK; this template exists so the testbed's
// subprocess contract has a Java implementation to exercise.

package com.a2atestbed.template;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class Main {

    public static void main(String[] args) throws IOException {
        String cardPath = null, scriptsPath = null, host = "127.0.0.1";
        int port = 0;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--agent-card": cardPath = args[++i]; break;
                case "--scripts":    scriptsPath = args[++i]; break;
                case "--port":       port = Integer.parseInt(args[++i]); break;
                case "--host":       host = args[++i]; break;
                default: /* ignore unknown */ break;
            }
        }
        if (cardPath == null || scriptsPath == null) {
            System.err.println("usage: java -jar agent.jar --agent-card <path> "
                    + "--scripts <path> [--port N]");
            System.exit(2);
        }

        final String cardText = new String(Files.readAllBytes(Path.of(cardPath)),
                StandardCharsets.UTF_8);
        final String scriptsText = new String(Files.readAllBytes(Path.of(scriptsPath)),
                StandardCharsets.UTF_8);
        final String agentId = firstGroupOr(cardText,
                "\"name\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"", "agent");
        final Map<String, String> scripts = parseFlatStringMap(scriptsText);

        HttpServer server = HttpServer.create(new InetSocketAddress(host, port), 0);
        server.createContext("/", exchange -> handle(exchange, cardText, scripts, agentId));
        server.setExecutor(null);
        server.start();

        int boundPort = server.getAddress().getPort();
        System.out.println("A2A_TESTBED_READY: http://" + host + ":" + boundPort);
        System.out.flush();

        Runtime.getRuntime().addShutdownHook(new Thread(() -> server.stop(0)));
    }

    private static void handle(HttpExchange exchange, String cardText,
                               Map<String, String> scripts, String agentId)
            throws IOException {
        String method = exchange.getRequestMethod();
        String path = exchange.getRequestURI().getPath();

        if ("GET".equals(method) && path.endsWith("/.well-known/agent-card.json")) {
            writeJson(exchange, 200, cardText);
            return;
        }
        if (!"POST".equals(method)) {
            exchange.sendResponseHeaders(404, -1);
            exchange.close();
            return;
        }

        String body = new String(exchange.getRequestBody().readAllBytes(),
                StandardCharsets.UTF_8);
        String id = firstGroupOr(body,
                "\"id\"\\s*:\\s*(\"(?:[^\"\\\\]|\\\\.)*\"|-?\\d+(?:\\.\\d+)?|null|true|false)",
                "null");
        String rpcMethod = firstGroupOr(body, "\"method\"\\s*:\\s*\"([^\"]+)\"", "");

        if (!"message/send".equals(rpcMethod)) {
            writeJson(exchange, 200, "{\"jsonrpc\":\"2.0\",\"id\":" + id
                    + ",\"error\":{\"code\":-32601,\"message\":\"unknown method "
                    + escape(rpcMethod) + "\"}}");
            return;
        }

        String text = extractText(body);
        String response = matchScript(text, scripts);
        String out = "{\"jsonrpc\":\"2.0\",\"id\":" + id + ",\"result\":{"
                + "\"kind\":\"message\","
                + "\"messageId\":\"resp-" + stripQuotes(id) + "\","
                + "\"role\":\"assistant\","
                + "\"parts\":[{\"kind\":\"text\",\"text\":\""
                + escape("[" + agentId + "] " + response) + "\"}]}}";
        writeJson(exchange, 200, out);
    }

    // -- helpers ---------------------------------------------------------

    /** Gather every "text":"..." value in the message and join with spaces. */
    private static String extractText(String body) {
        Matcher m = Pattern.compile("\"text\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"")
                .matcher(body);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            if (sb.length() > 0) sb.append(' ');
            sb.append(unescape(m.group(1)));
        }
        return sb.toString();
    }

    /** First case-insensitive key substring match, else "received: ...". */
    private static String matchScript(String text, Map<String, String> scripts) {
        String lower = text == null ? "" : text.toLowerCase();
        for (Map.Entry<String, String> e : scripts.entrySet()) {
            if (lower.contains(e.getKey().toLowerCase())) return e.getValue();
        }
        return "received: " + (text == null || text.isEmpty() ? "(empty)" : text);
    }

    private static Map<String, String> parseFlatStringMap(String json) {
        Map<String, String> out = new LinkedHashMap<>();
        Matcher m = Pattern.compile(
                "\"((?:[^\"\\\\]|\\\\.)*)\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"")
                .matcher(json);
        while (m.find()) {
            out.put(unescape(m.group(1)), unescape(m.group(2)));
        }
        return out;
    }

    private static String firstGroupOr(String s, String regex, String fallback) {
        Matcher m = Pattern.compile(regex).matcher(s);
        return m.find() ? m.group(1) : fallback;
    }

    private static String stripQuotes(String s) {
        if (s.length() >= 2 && s.startsWith("\"") && s.endsWith("\"")) {
            return s.substring(1, s.length() - 1);
        }
        return s;
    }

    private static String unescape(String s) {
        return s.replace("\\\"", "\"").replace("\\\\", "\\")
                .replace("\\n", "\n").replace("\\t", "\t");
    }

    private static String escape(String s) {
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':  sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.toString();
    }

    private static void writeJson(HttpExchange exchange, int status, String body)
            throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    private Main() {}
}
