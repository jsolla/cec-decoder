# Sigrok HDMI CEC protocol decoder
Sigrok protocol decoder for HDMI CEC (Consumer Electronics Control)

Consumer Electronics Control (CEC) is a feature of HDMI designed to allow users to command and control devices connected through HDMI

CEC Bus can be found in PIN 13 of the HDMI connector:
![Hdmi pinout](hdmi_pinout.png)

Pulseview capture: CEC Ping frames
![Pulseview screenshot cec_decoder](screenshot1.png)

Pulseview capture: Vendor comand frame
![Pulseview screenshot cec_decoder](screenshot2.png)