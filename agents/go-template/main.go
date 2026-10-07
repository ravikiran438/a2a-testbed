// Copyright 2026 Ravi Kiran Kadaboina
// Licensed under the Apache License, Version 2.0.
//
// Go reference agent for the a2a-testbed subprocess runtime.
//
// Reads CLI args --agent-card, --scripts, --port; binds an HTTP
// server on 127.0.0.1; serves the AgentCard at the well-known URL and
// a minimal JSON-RPC send endpoint. Prints
// "A2A_TESTBED_READY: <url>" on stdout when listening.
//
// Speaks A2A 1.0 (SendMessage with A2A-Version: 1.0; replies
// {"message": {...}} with ROLE_AGENT and oneof parts) and still answers
// A2A 0.3 callers (message/send; bare Message with kind discriminators).
//
// Uses stdlib net/http only. Real production Go agents would swap to
// github.com/a2aproject/a2a-go for full A2A compliance.

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"regexp"
	"strings"
)

type jsonrpcRequest struct {
	Jsonrpc string          `json:"jsonrpc"`
	ID      any             `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params"`
}

type messagePart struct {
	Kind string `json:"kind"`
	Text string `json:"text"`
}

type message struct {
	MessageID string        `json:"messageId"`
	Role      string        `json:"role"`
	Parts     []messagePart `json:"parts"`
}

type sendParams struct {
	Message message `json:"message"`
}

func main() {
	cardPath := flag.String("agent-card", "", "Path to AgentCard JSON")
	scriptsPath := flag.String("scripts", "", "Path to scripts JSON")
	port := flag.Int("port", 0, "Bind port (0 = random)")
	host := flag.String("host", "127.0.0.1", "Bind host")
	flag.Parse()

	if *cardPath == "" || *scriptsPath == "" {
		fmt.Fprintln(os.Stderr, "usage: go run . --agent-card <path> --scripts <path> [--port N]")
		os.Exit(2)
	}

	cardRaw, err := os.ReadFile(*cardPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "reading agent-card: %v\n", err)
		os.Exit(1)
	}
	var cardObj map[string]any
	if err := json.Unmarshal(cardRaw, &cardObj); err != nil {
		fmt.Fprintf(os.Stderr, "parsing agent-card: %v\n", err)
		os.Exit(1)
	}
	scriptsRaw, err := os.ReadFile(*scriptsPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "reading scripts: %v\n", err)
		os.Exit(1)
	}
	var scripts map[string]string
	if err := json.Unmarshal(scriptsRaw, &scripts); err != nil {
		fmt.Fprintf(os.Stderr, "parsing scripts: %v\n", err)
		os.Exit(1)
	}
	agentID, _ := cardObj["name"].(string)
	if agentID == "" {
		agentID = "agent"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/.well-known/agent-card.json", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("content-type", "application/json")
		_ = json.NewEncoder(w).Encode(cardObj)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.NotFound(w, r)
			return
		}
		var req jsonrpcRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSONRPCError(w, nil, -32700, "parse error")
			return
		}
		if req.Method != "SendMessage" && req.Method != "message/send" {
			writeJSONRPCError(w, req.ID, -32601, fmt.Sprintf("unknown method %q", req.Method))
			return
		}
		if req.Method == "SendMessage" && !requestsV1(r.Header.Get("A2A-Version")) {
			// A2A 1.0 §3.6.2: an absent header means 0.3, which has no SendMessage.
			writeJSONRPCError(w, req.ID, -32009, "SendMessage requires A2A-Version: 1.0")
			return
		}
		var params sendParams
		_ = json.Unmarshal(req.Params, &params)
		text := extractText(params)
		reply := fmt.Sprintf("[%s] %s", agentID, matchScript(text, scripts))
		messageID := fmt.Sprintf("resp-%v", req.ID)
		if req.Method == "SendMessage" {
			writeJSONRPC(w, req.ID, map[string]any{
				"message": map[string]any{
					"messageId": messageID,
					"role":      "ROLE_AGENT",
					"parts":     []map[string]any{{"text": reply}},
				},
			})
			return
		}
		writeJSONRPC(w, req.ID, map[string]any{
			"kind":      "message",
			"messageId": messageID,
			"role":      "agent",
			"parts":     []map[string]any{{"kind": "text", "text": reply}},
		})
	})

	addr := fmt.Sprintf("%s:%d", *host, *port)
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		fmt.Fprintf(os.Stderr, "listen %s: %v\n", addr, err)
		os.Exit(1)
	}
	bound := listener.Addr().(*net.TCPAddr)
	fmt.Printf("A2A_TESTBED_READY: http://%s:%d\n", *host, bound.Port)
	if err := http.Serve(listener, mux); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

// requestsV1 reports whether an A2A-Version header value names a 1.x
// version (comma-separated values allowed; an absent header means 0.3).
func requestsV1(header string) bool {
	for _, v := range strings.Split(header, ",") {
		if v1Version.MatchString(strings.TrimSpace(v)) {
			return true
		}
	}
	return false
}

var v1Version = regexp.MustCompile(`^1(\.\d+)*$`)

func extractText(p sendParams) string {
	chunks := []string{}
	for _, part := range p.Message.Parts {
		if part.Text != "" {
			chunks = append(chunks, part.Text)
		}
	}
	return strings.Join(chunks, " ")
}

func matchScript(text string, scripts map[string]string) string {
	lower := strings.ToLower(text)
	for key, value := range scripts {
		if strings.Contains(lower, strings.ToLower(key)) {
			return value
		}
	}
	if text == "" {
		return "received: (empty)"
	}
	return "received: " + text
}

func writeJSONRPC(w http.ResponseWriter, id any, result any) {
	w.Header().Set("content-type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"jsonrpc": "2.0",
		"id":      id,
		"result":  result,
	})
}

func writeJSONRPCError(w http.ResponseWriter, id any, code int, message string) {
	w.Header().Set("content-type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"jsonrpc": "2.0",
		"id":      id,
		"error": map[string]any{
			"code":    code,
			"message": message,
		},
	})
}
