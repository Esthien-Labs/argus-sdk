// Evaluate one safety-envelope decision window with the Argus SDK Go wrapper.
package main

import (
	"fmt"

	argus "github.com/esthien/argus-go"
)

func main() {
	envelope, err := argus.NewSafetyEnvelope(argus.DefaultSafetyConfig())
	if err != nil {
		panic(err)
	}
	defer envelope.Close()

	command, err := envelope.Evaluate(
		argus.Prediction{Intent: "knee_flexion", Confidence: 0.92},
		argus.SignalQuality{Reliability: 0.95, FlatlineChannels: []uint32{}, ArtifactDetected: false},
	)
	if err != nil {
		panic(err)
	}

	fmt.Printf("state=%d\n", command.EnvelopeState)
	fmt.Printf("torqueNm=%f velocityRadS=%f\n", command.TorqueNm, command.VelocityRadS)
	fmt.Printf("effectiveConfidence=%f\n", command.EffectiveConfidence)
	fmt.Printf("nominal=%t\n", command.EnvelopeState == argus.Nominal)
}
