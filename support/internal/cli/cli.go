package cli

import (
	"context"
	"encoding/json"
	"flag"
	"io"
	"log"
	"os"
)

var (
	Context = context.Background()

	inited = false

	inputPath  string
	outputPath string
)

// Set up common CLI flags, etc. Calls flag.Parse.
func Init() {
	if inited {
		panic("Init may only be called once")
	}
	flag.StringVar(&inputPath, "input-json", "-", "Path to input, or '-' for stdin")
	flag.StringVar(&outputPath, "output-json", "-", "Path to output, or '-' for stdout")
	authFlags.Register(flag.CommandLine, authOptions)
	flag.Parse()
	inited = true
}

func assertInited(afterInit bool) {
	if inited != afterInit {
		if afterInit {
			log.Fatal("must be called after Init")
		} else {
			log.Fatal("must be called before Init")
		}
	}
}

// Unmarshal input into the given type or die.
func MustUnmarshalInput(v interface{}) {
	assertInited(true)
	var r io.ReadCloser
	if inputPath == "" || inputPath == "-" {
		r = os.Stdin
	} else {
		var err error
		r, err = os.Open(inputPath)
		if err != nil {
			log.Fatalf("failed to open input: %v", err)
		}
	}
	defer r.Close()
	decoder := json.NewDecoder(r)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(v); err != nil {
		log.Fatalf("failed to decode input: %v", err)
	}
}

// Marshal given data to output or die.
func MustMarshalOutput(v interface{}) {
	assertInited(true)
	var w io.WriteCloser
	if outputPath == "" || outputPath == "-" {
		w = os.Stdout
	} else {
		var err error
		w, err = os.Create(outputPath)
		if err != nil {
			log.Fatalf("failed to open output: %v", err)
		}
	}
	defer w.Close()
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Fatalf("failed to encode output: %v", err)
	}
}
