package shared

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestDoWithRetry_error(t *testing.T) {
	opts := Options{
		BackoffBase: 0,
		BaseDelay:   0 * time.Second,
		Retries:     5,
	}
	err := DoWithRetry(context.Background(), opts, func() error {
		return errors.New("throw!")
	})
	if err == nil {
		t.Errorf("Expected an error, but got none")
	}
}

func TestDoWithRetry_success(t *testing.T) {
	opts := Options{
		BackoffBase: 0,
		BaseDelay:   0 * time.Second,
		Retries:     5,
	}
	err := DoWithRetry(context.Background(), opts, func() error {
		return nil
	})
	if err != nil {
		t.Errorf("Expected no error, but got %v", err)
	}
}
