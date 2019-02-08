package main

import (
	"bufio"
	"flag"
	"io"
	"log"
	"os"
	"os/exec"
	"strings"
	"sync"
)

var (
	traceFile string
	repoBin   string
)

func init() {
	flag.StringVar(&traceFile, "trace-file", "", "trace file path to write")
	flag.StringVar(&repoBin, "repo-bin", "repo", "repo bin to execute ")
}

type outputHandler struct {
	wg            sync.WaitGroup
	writeLock     sync.Mutex
	stdout        io.Writer
	trace         io.Writer
	skippedBlanks int
}

func (h *outputHandler) Handle(stdout, stderr io.Reader) {
	h.wg.Add(2)
	go h.processStream(stdout, false)
	go h.processStream(stderr, true)
	h.wg.Wait()
}

func (h *outputHandler) processStream(r io.Reader, hasTrace bool) {
	defer h.wg.Done()
	buf := bufio.NewReader(r)
	for {
		line, err := buf.ReadString('\n')
		h.writeLine(line, hasTrace)
		if err != nil {
			if err != io.EOF {
				log.Printf("ReadString: %v", err)
			}
			break
		}
	}
}

func (h *outputHandler) writeLine(line string, trace bool) {
	h.writeLock.Lock()
	defer h.writeLock.Unlock()

	// Write everything to the trace file.
	if h.trace != nil {
		if _, err := io.WriteString(h.trace, line); err != nil {
			log.Printf("error logging to trace file; stopping trace: %v", err)
			h.trace = nil
		}
	}

	// Skip trace lines and blank lines immediately preceding trace lines for stdout.
	if strings.HasPrefix(line, ": ") {
		h.skippedBlanks = 0
	} else if line == "\n" {
		h.skippedBlanks += 1
	} else {
		var err error
		// Write previously skipped blank lines.
		if h.skippedBlanks > 0 {
			_, err = io.WriteString(h.stdout, strings.Repeat("\n", h.skippedBlanks))
			h.skippedBlanks = 0
		}
		if err == nil {
			_, err = io.WriteString(h.stdout, line)
		}
		if err != nil {
			log.Fatalf("error writing to stdout: %v", err)
		}
	}
}

func main() {
	log.SetPrefix("repo-log-trace: ")
	flag.Parse()
	if traceFile == "" {
		log.Fatal("--trace-file required")
	}

	trace, err := os.Create(traceFile)
	if err != nil {
		log.Fatalf("error creating --trace-file %s: %v", traceFile, err)
	}
	defer trace.Close()

	if err := os.Setenv("REPO_TRACE", "1"); err != nil {
		log.Fatalf("Error setting REPO_TRACE: %v", err)
	}
	if err := os.Setenv("PYTHONUNBUFFERED", "1"); err != nil {
		log.Fatalf("Error setting PYTHONUNBUFFERED: %v", err)
	}

	cmd := exec.Command(repoBin, flag.Args()...)

	handler := &outputHandler{
		stdout: os.Stdout,
		trace:  trace,
	}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		log.Fatalf("StdoutPipe: %v", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		log.Fatalf("StderrPipe: %v", err)
	}
	if err := cmd.Start(); err != nil {
		log.Fatalf("failed to execute %s: %v", repoBin, err)
	}

	handler.Handle(stdout, stderr)

	if err := cmd.Wait(); err != nil {
		if _, isExitErr := err.(*exec.ExitError); !isExitErr {
			log.Printf("Wait: %v", err)
		}
	}

	os.Exit(cmd.ProcessState.ExitCode())
}
