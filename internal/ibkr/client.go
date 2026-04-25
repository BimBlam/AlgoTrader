// Package ibkr implements the Interactive Brokers TWS API client.
//
// This is a placeholder for the Go migration.  The Python implementation
// lives in algotrader/execution/ibkr_client.py (ib_insync).
package ibkr

import "fmt"

// Client connects to TWS/Gateway and submits orders.
type Client struct {
	Host string
	Port int
}

func New(host string, port int) *Client {
	return &Client{Host: host, Port: port}
}

func (c *Client) Connect() error {
	fmt.Printf("ibkr: connect to %s:%d (placeholder)\n", c.Host, c.Port)
	return nil
}

func (c *Client) Disconnect() {
	fmt.Println("ibkr: disconnected (placeholder)")
}
