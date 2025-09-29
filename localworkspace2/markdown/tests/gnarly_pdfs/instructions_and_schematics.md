Limited Warranty

The EZ-KIT Lite evaluation system is warranted against defects in materials and workmanship for a period of one year from the date of purchase from Analog Devices or from an authorized dealer.

Disclaimer

Analog Devices, Inc. reserves the right to change this product without prior notice. Information furnished by Analog Devices is believed to be accurate and reliable. However, no responsibility is assumed by Analog Devices for its use; nor for any infringement of patents or other rights of third parties, which may result from its use. No license is granted by implication or otherwise under the patents rights of Analog Devices, Inc.

Copyright Information

Copyright 2001, Analog Devices, Inc., ALL RIGHTS RESERVED. This document may not be reproduced in any form without prior, express written consent from Analog Devices, Inc.

Trademark and Service Mark Notice

EZ-KIT Lite, VisualDSP++, VisualDSP++ logo, TigerSHARC, TigerSHARC logo, CROSSCORE, CROSSCORE logo, Blackfin and the Blackfin logo are all trademarks of Analog Devices Inc. EZ-ICE, SHARC and the SHARC logo are registered trademarks of Analog Devices, Inc. All trademarks and logos are property of their respective holders.

Microsoft and Windows are registered trademarks of Microsoft Corporation.

Adobe and Acrobat are trademarks of Adobe Systems Incorporated.

All other brand and product names are trademarks or service marks of their respective owners.
Regulatory Compliance

The ADSP-21161N EZ-KIT Lite evaluation system has been certified to comply with the essential requirements of the European EMC directive 89/336/EEC (inclusive 93/68/EEC) and therefore carries the “CE” mark.

The ADSP-21161N EZ-KIT Lite evaluation system had been appended to the Technical Construction File referenced ‘DSPTOOLS1’ dated December 21, 1997 and was awarded CE Certification by an appointed European Competent Body as listed below.

Technical Certificate No: Z600ANA1.005

Issued by: Technology International (Europe) Limited
41 Shrivenham Hundred Business Park
Shrivenham, Swindon, SN6 8TZ, UK

The EZ-KIT Lite evaluation system contains ESD (electrostatic discharge) sensitive devices. Electrostatic charges readily accumulate on the human body and equipment and can discharge without detection. Permanent damage may occur on devices subjected to high-energy discharges. Proper ESD precautions are recommended to avoid performance degradation or loss of functionality. Store used EZ-KIT Lite boards in the protective shipping package.
# TABLE OF CONTENTS

| Section                                                                 | Page |
|------------------------------------------------------------------------|------|
| TABLE OF CONTENTS                                                      | iv   |
| LIST OF TABLES                                                         | vi   |
| LIST OF FIGURES                                                        | vi   |
| 1 INTRODUCTION                                                          | 1-1  |
| 1.1 For More Information About Analog Devices Products                 | 1-2  |
| 1.2 For Technical or Customer Support                                  | 1-3  |
| 1.3 Purpose of This Manual                                             | 1-3  |
| 1.4 Intended Audience                                                  | 1-3  |
| 1.5 Manual Contents                                                    | 1-4  |
| 1.6 On-line Help                                                       | 1-4  |
| 2 GETTING STARTED                                                      | 2-1  |
| 2.1 Overview                                                           | 2-1  |
| 2.2 Contents of your EZ-KIT Lite Package                               | 2-1  |
| 2.3 PC Configuration                                                   | 2-2  |
| 2.4 Installation Tasks                                                 | 2-2  |
| 2.4.1 Install the VisualDSP++ Software                                 | 2-2  |
| 2.4.2 Install the VisualDSP++ License                                  | 2-3  |
| 2.4.3 Install the EZ-KIT Lite Debug Software                           | 2-3  |
| 2.4.4 Set-up the EZ-KIT Lite Hardware                                  | 2-4  |
| 2.4.5 Install the EZ-KIT Lite USB Driver                               | 2-5  |
| 2.4.6 Driver Installation Verification                                 | 2-15 |
| 2.4.7 Starting VisualDSP++                                             | 2-16 |
| 3 USING THE EZ-KIT LITE                                                | 3-1  |
| 3.1 Overview                                                           | 3-1  |
| 3.2 EZ-KIT Lite License Restrictions                                   | 3-2  |
| 3.3 Memory Map                                                         | 3-2  |
| 3.4 Using the SDRAM Interface                                          | 3-3  |
| 3.5 Using the Flag Pins                                                | 3-4  |
| 3.6 Using the Interrupt Pins                                           | 3-5  |
| 3.7 Using the Audio Interface                                          | 3-5  |
| 3.8 Example Programs                                                   | 3-6  |
| 3.9 Using the Flash Programmer Utility                                 | 3-6  |
| 4 EZ-KIT LITE HARDWARE REFERENCE                                       | 4-1  |
| 4.1 Overview                                                           | 4-1  |
| 4.2 System Architecture                                                | 4-2  |
| 4.2.1 External Port                                                    | 4-3  |
| 4.2.2 Host Processor Interface (HPI)                                   | 4-3  |
| 4.2.3 SPORT0 and SPORT2 – Audio Interface                              | 4-3  |
| 4.2.4 SPI - Audio Interface                                            | 4-3  |
| 4.2.5 Breadboard Area                                                  | 4-4  |
| 4.2.6 JTAG Emulation Port                                              | 4-4  |
| 4.3 Jumper Settings                                                    | 4-4  |
| 4.3.1 SDRAM Disable (JP1)                                              | 4-5  |
| 4.3.2 SPDIF Selection Jumper (JP2)                                     | 4-6  |
| Section | Description | Page |
|---------|-------------|------|
| 4.3.3   | MCLK Selection Jumper (JP3) | 4-6  |
| 4.3.4   | FLAG0 Enable (JP4) | 4-6  |
| 4.3.5   | FLAG1 Enable (JP5) | 4-6  |
| 4.3.6   | Sample Frequency Jumper (JP6) | 4-6  |
| 4.3.7   | ADC2 Input Mode Selection Jumper (JP7 and JP8) | 4-7  |
| 4.3.8   | MIC Pre-Amp Gain Selection Jumpers (JP9 and JP10) | 4-7  |
| 4.3.9   | ADC1 Input Selector Jumper (JP11) | 4-7  |
| 4.3.10  | Processor ID Jumpers (JP19) | 4-8  |
| 4.3.11  | Boot Mode Select (JP20) | 4-8  |
| 4.3.12  | Clock Mode Jumpers (JP21) | 4-9  |
| 4.3.13  | BMS Enable (JP22) | 4-10 |
| 4.4     | LEDs and Push Buttons | 4-10 |
| 4.4.1   | Reset LEDs (LED1, LED8) | 4-11 |
| 4.4.2   | FLAG LEDs (LED2 - LED7) | 4-12 |
| 4.4.3   | VERF LED (LED9) | 4-12 |
| 4.4.4   | USB Monitor LED (LED10) | 4-12 |
| 4.4.5   | Power LED (LED11) | 4-12 |
| 4.4.6   | Programmable Flag Push Buttons (SW1 – SW4) | 4-13 |
| 4.4.7   | Interrupt Push Buttons (SW5 – SW7) | 4-13 |
| 4.4.8   | Reset Push Button (SW8) | 4-13 |
| 4.5     | Connectors | 4-14 |
| 4.5.1   | USB (P2) | 4-14 |
| 4.5.2   | Audio (P4 – P8, P17) | 4-14 |
| 4.5.3   | External port and Host Processor Interface (P9, and P10) | 4-15 |
| 4.5.4   | JTAG (P12) | 4-15 |
| 4.5.5   | Link Ports (P13 and P14) | 4-15 |
| 4.5.6   | SPORT1 and SPORT3 (P15) | 4-16 |
| 4.5.7   | Power Connector (P16) | 4-16 |
| 4.6     | Specifications | 4-16 |
| 4.6.1   | Power Supply | 4-16 |
| 4.6.2   | Board Current Measurements | 4-17 |
| APPENDIX A: BILL OF MATERIALS | A |
| APPENDIX B: SCHEMATIC | E |
| INDEX | 1 |
LIST OF TABLES

Table 1-1: Related DSP Documents ................................................................. 1-5
Table 1-2: Related VisualDSP++ Documents .................................................. 1-6
Table 2-1: Minimum PC Configuration ............................................................ 2-2
Table 3-1: EZ-KIT Lite Evaluation Board Memory Map ................................... 3-3
Table 3-2: Flag Pin Summary ............................................................................. 3-4
Table 3-3: Interrupt Pin Summary ....................................................................... 3-5
Table 4-1: SPDIF Modes ...................................................................................... 4-6
Table 4-2: MCLK Selection ................................................................................ 4-6
Table 4-3: Sample Frequencies .......................................................................... 4-7
Table 4-4: ADC Input Mode ................................................................................ 4-7
Table 4-5: MIC Pre Amp Gain ........................................................................... 4-7
Table 4-6: Processor ID Modes ........................................................................... 4-8
Table 4-7: Boot Mode Select Jumper (JP20) Settings ........................................ 4-9
Table 4-8: Clock Mode Selections ....................................................................... 4-9
Table 4-9: FLAG LEDs ....................................................................................... 4-12
Table 4-10: FLAG Switches ............................................................................... 4-13
Table 4-11: Interrupt Switches ........................................................................... 4-13
Table 4-12: Power Connector ............................................................................ 4-17
Table 4-13: Current Measurement Resistors ...................................................... 4-17

LIST OF FIGURES

Figure 2-1: EZ-KIT Lite Hardware Setup ............................................................ 2-5
Figure 2-2: Add New Hardware Wizard Dialog Box ........................................... 2-6
Figure 2-3: Search for the driver ......................................................................... 2-7
Figure 2-4: Search the CD-ROM ......................................................................... 2-7
Figure 2-5: The driver is located ......................................................................... 2-8
Figure 2-6: Search for .sys File Dialog Box ....................................................... 2-8
Figure 2-7: Open the .sys File ............................................................................ 2-9
Figure 2-8: Copying Files ................................................................................... 2-9
Figure 2-9: Finish the Software Installation ....................................................... 2-10
Figure 2-10: Found New Hardware Wizard ....................................................... 2-11
Figure 2-11: Search for a Suitable Driver ........................................................... 2-12
Figure 2-12: Locate Driver Files ......................................................................... 2-13
Figure 2-13: Driver File Search Results ............................................................. 2-14
Figure 2-14: Completing Driver Installation Dialog Box ..................................... 2-15
Figure 2-15: New Session Dialog Box ............................................................... 2-16
Figure 3-1 Target Options ................................................................................... 3-4
Figure 4-1: System Architecture ......................................................................... 4-2
Figure 4-2: Jumper Locations ............................................................................. 4-5
Figure 4-3: Audio Input Jumper Settings ............................................................ 4-8
Figure 4-4: LEDs and Push Button Locations ..................................................... 4-11
Figure 4-5: Connector Locations ......................................................................... 4-14
1 INTRODUCTION

Thank you for purchasing the ADSP-21161N EZ-KIT Lite™ evaluation system. The evaluation board is designed to be used in conjunction with the VisualDSP++™ development environment to test the capabilities of the ADSP-21161N floating-point digital signal processor (DSP). The VisualDSP++ development environment gives you the ability to perform advanced application code development and debug such as:

- Create, compile, assemble, and link application programs written in C++, C and ADSP-2116x assembly
- Load, run, step-in, step-out, step-over, halt, and set breakpoints in application programs
- Read and write data and program memory
- Read and write core and peripheral registers
- Plot memory

Access to the ADSP-21161N, from a PC, is achieved through a USB port or an optional JTAG emulator. The USB interface gives unrestricted access to the ADSP-21161N DSP and the evaluation board peripherals. Analog Devices JTAG emulators offer faster communication between the host PC and target hardware. Analog Devices carries a wide range of in-circuit emulation products. To learn more about Analog Devices emulators and DSP development tools, go to http://www.analog.com/dsp/tools/.

Example programs are provided in the ADSP-21161N EZ-KIT Lite, which demonstrate the capabilities of the evaluation board.

Note: The VisualDSP++ license provided with this EZ-KIT Lite evaluation system limits the use of program memory to 5k words.

The board’s features include:

- **Analog Devices ADSP-21161N DSP**
  - 100MHz Core Clock Speed
  - Core Clock Mode Jumper Configurable.
- **USB Debugging Interface**
• **Analog Devices AD1836 96kHz Audio Codec**
  - Jumper Selectable Line-In or Mic-In 3.5mm Stereo Jack
  - Line-Out 3.5mm Stereo Jack
  - 4 RCA Jacks for Audio Input
  - 8 RCA Jacks for Audio Output

• **Analog Devices AD1852 192kHz Auxiliary DAC**

• **Crystal Semiconductor CS8414 96kHz SPDIF Receiver**
  - Optical and Coaxial Connectors for SPDIF Input

• **Flash Memory**
  - 512K x 8

• **Interface Connectors**
  - 14-Pin Emulator Connector for JTAG Interface
  - SPORT1 and SPORT3 Connectors
  - Link Port 0 and Link Port 1
  - External Port Connectors (not populated)

• **General Purpose I/O**
  - 4 Push Button Flags
  - 3 Push Button Interrupts
  - 6 LED Outputs

• **Analog Devices ADP3338 & ADP3339 Voltage Regulators**

• **Breadboard area with typical SMT footprints**

The EZ-KIT Lite board has a flash memory device that can be used to store user specific boot code. By configuring the jumpers for EPROM boot, the board can run as a stand-alone unit, without a PC. The ADSP-21161N EZ-KIT Lite package contains a flash programmer utility, which allows you to program the flash memory. The flash programmer is described in section 3.9.

SPORT0 and SPORT2 are connected to the audio codec, allowing you to create audio signal processing applications. SPORT1 and SPORT3 are connected to off-board connectors to connect to other serial devices.

Additionally, the EZ-KIT Lite board provides un-installed expansion connector footprints that allow you to connect to the processor’s External Port (EP) and Host Processor Interface (HPI).

1.1 For More Information About Analog Devices Products

Analog Devices can be accessed on the Internet at [http://www.analog.com](http://www.analog.com). You can directly access the DSP web pages at [http://www.analog.com/dsp](http://www.analog.com/dsp). This page provides access to DSP specific technical information and documentation, product overviews, and product announcements. For specific information about DSP tools, go to [http://www.analog.com/dsp/tools](http://www.analog.com/dsp/tools).
21161N EZ-KIT LITE
To view help on additional ADSP-21161N EZ-KIT Lite features, go to the windows task bar and select Start\Programs\VisualDSP\EZ-KIT Help.

The documents in the following two tables can be found through on-line help or in the Docs folder of your VisualDSP++ installation.

For more documentation, please go to http://www.analog.com/dsp/tech_doc

Table 1-1: Related DSP Documents

| Document Name                                      | Description                                                                 |
|----------------------------------------------------|-----------------------------------------------------------------------------|
| ADSP-21161N DSP Datasheet                          | General functional description, pinout and timing.                           |
| ADSP-21161N SHARC DSP Hardware Reference           | Description of internal DSP architecture and all register functions.         |
| ADSP-21160 DSP Instruction Set Reference           | Description of all allowed DSP assembly instructions.                        |
| ADSP-21161 Programmer's Quick Reference Manual     | Provides a summary of the ADSP-2116x instruction set, core and IOP registers, memory maps, a DEF21161.H file listing, and common VisualDSP tools commands." |
Table 1-2: Related VisualDSP++ Documents

| Document Name                                                                 | Description                                                                 |
|------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| *VisualDSP++ Users Guide for ADSP-21xx DSPs*                                 | Detailed description of VisualDSP++ features and usage.                     |
| *VisualDSP++ Preprocessor and Assembler Manual for ADSP-21xx DSPs*           | Description of the assembler function and commands for ADSP-2116x family DSPs|
| *VisualDSP++ C/C++ Complier and Library Manual for ADSP-21xx DSPs*           | Description of the complier function and commands for ADSP-2116x family DSPs|
| *VisualDSP++ Linker and Utilities Manual for ADSP-21xx DSPs*                  | Description of the linker function and commands for the ADSP-2116x family DSPs|

If you plan to use the EZ-KIT Lite board in conjunction with a JTAG emulator, refer to the documentation that accompanies the emulator.
2 GETTING STARTED

2.1 Overview
This chapter provides you with the information you need to begin using ADSP-21161N EZ-KIT Lite evaluation system. Install your software and hardware in the order presented in section 2.4 for correct operation. This chapter has the following sections:

- **Contents of your EZ-KIT Lite Package** (Section 2.2)
  Provides a list of the components that are shipped with this EZ-KIT Lite evaluation system.

- **PC Configuration** (Section 2.3)
  Describes the minimum requirement for the PC to work with the EZ-KIT Lite evaluation system.

- **Installation Tasks** (Section 2.4)
  Describes the step-by-step procedure for setting up the hardware and software.

2.2 Contents of your EZ-KIT Lite Package
Your ADSP-21161N EZ-KIT Lite evaluation system package contains the following items.

- ADSP-21161N EZ-KIT Lite board
- VisualDSP++ CD w/ license.
- ADSP-21161N EZ-KIT Lite CD, containing:
  - EZ-KIT Lite specific debug software
  - USB driver files
  - Example programs
  - ADSP-21161N EZ-KIT Lite Manual (this document)
  - Flash programmer utility
- EZ-KIT Lite Quick Start Guide
- Installation Quick Reference Card for VisualDSP++
- Universal 7.5V DC power supply
- 5 meter USB type A to type B cable
- Registration card - please fill out and return

If any item is missing, contact the vendor where you purchased your EZ-KIT Lite or contact Analog Devices, Inc.
The EZ-KIT Lite evaluation system contains ESD (electrostatic discharge) sensitive devices. Electrostatic charges readily accumulate on the human body and equipment and can discharge without detection. Permanent damage may occur on devices subjected to high-energy discharges. Proper ESD precautions are recommended to avoid performance degradation or loss of functionality. Store used EZ-KIT Lite boards in the protective shipping package.

2.3 PC Configuration

For correct operation of the VisualDSP++ software and the EZ-KIT Lite, your computer must have the minimum configuration shown in Table 2-1.

Table 2-1: Minimum PC Configuration

| Windows® 98, Windows® 2000 or later |
|-------------------------------------|
| Intel (or comparable) 166MHz processor |
| VGA Monitor and color video card |
| 2-button mouse |
| 50MB free on hard drive |
| 32 MB RAM |
| Full speed USB port |
| CD-ROM Drive |

 Note: This EZ-KIT Lite does not run under Windows 95 or Windows NT

2.4 Installation Tasks

The following tasks are provided for the safe and effective use of the ADSP-21161N EZ-KIT Lite. Follow these instructions in the order presented to ensure correct operation of your software and hardware.

1. Install VisualDSP++ software
2. Install VisualDSP++ license
3. Install EZ-KIT Lite debug software
4. Setup EZ-KIT Lite hardware
5. Install EZ-KIT Lite USB driver
6. Verify the USB driver installation
7. Start VisualDSP++

2.4.1 Install the VisualDSP++ Software

This EZ-KIT Lite comes with the latest version of VisualDSP++ for the SHARC DSP family. You must install this software before installing the EZ-KIT Lite debug software.
Insert the VisualDSP++ CD-ROM into the CD-ROM drive. If Auto Run is enabled on your PC, the home screen of the VisualDSP++ install wizard will automatically appear. If not, choose **Run** from the **Start** menu, and enter **D:\Setup.exe** in the **Open** field, where D is the name of your local CD-ROM drive. Click on the “Install VisualDSP++” option. This will launch the setup wizard. Follow the on-screen instructions.

### 2.4.2 Install the VisualDSP++ License

Before the VisualDSP++ software can be used, the license must be installed.

To install the VisualDSP++ license:

1. Make sure VisualDSP++ has been installed first.
2. Insert the VisualDSP++ CD-ROM into the CD-ROM drive if it is not already in the drive.
3. Once the CD-ROM browser is on the screen select the “Install License” option.
4. Follow the setup wizard instructions. (Note: You will need the serial number located on the back of the CD-ROM sleeve.)

### 2.4.3 Install the EZ-KIT Lite Debug Software

VisualDSP++ communicates with the EZ-KIT Lite board using the EZ-KIT Lite debug software. This software is supplied on the EZ-KIT Lite CD-ROM.

To install the EZ-KIT Lite debug software:

1. Make sure VisualDSP++ has been installed first.
2. Close all Windows applications. The install will not work correctly if any VisualDSP++ applications are running.
3. Insert the EZ-KIT Lite CD-ROM into the CD-ROM drive. If Auto Run is enabled on your PC, the home screen of the EZ-KIT Lite install wizard will automatically appear. If not, choose **Run** from the **Start** menu, and enter **D:\Setup.exe** in the **Open** field, where D is the name of your local CD-ROM drive. Click on the “Install EZ-KIT Lite Software” option. This will launch the setup wizard. Follow this wizard with the on-screen instructions.
2.4.4 Set-up the EZ-KIT Lite Hardware

The EZ-KIT Lite Evaluation board contains ESD (electrostatic discharge) sensitive devices. Electrostatic charges readily accumulate on the human body and equipment and can discharge without detection. Permanent damage may occur on devices subjected to high energy discharges. Proper ESD precautions are recommended to avoid performance degradation or loss of functionality. Store used EZ-KIT Lite boards in the protective shipping package.

The ADSP-21161N EZ-KIT Lite board is designed to run outside your personal computer as a stand-alone unit. You do not have to open your computer case. Use the following steps to connect the EZ-KIT Lite board:

1. Remove the EZ-KIT Lite board from the package. Be careful when handling these boards to avoid the discharge of static electricity, which may damage some components.

2. Figure 2-1 shows the default jumper settings, connector locations and LEDs used in installation. Confirm that your board is set up in the default configuration before continuing.
3. Plug the provided power supply into P16 on the EZ-KIT Lite board. Visually verify that the green power LED (LED11) is on. Also verify that the two red reset LEDs (LED1 and LED8) go on for a moment and then go off.

4. Connect the USB cable to an available full speed USB Port and to P2 on the ADSP-21161N EZ-KIT Lite board.

5. Now follow the USB driver installation instructions in section 2.4.5.

2.4.5 Install the EZ-KIT Lite USB Driver

The EZ-KIT Lite evaluation system can be installed on Windows 98 and Windows 2000 and requires one full-speed USB port. Section 2.4.5.1 describes the installation on Windows 98. Section 2.4.5.2 describes the installation on Windows 2000.
2.4.5.1 Windows 98 USB Driver Installation

Before using the ADSP-21161N EZ-KIT Lite for the first time, the Windows 98 USB driver must first be installed. This is accomplished as follows:

1. Insert the EZ-KIT Lite CD-ROM into the CD-ROM drive.

The connection of the device to the USB port will activate the Windows 98 “Add New Hardware Wizard” as shown in Figure 2-2.

![Add New Hardware Wizard Dialog Box](image)

**Figure 2-2: Add New Hardware Wizard Dialog Box**

2. Click Next.
3. Select “Search for the best driver for your device” as shown in Figure 2-3.

![Add New Hardware Wizard](image1)

**Figure 2-3: Search for the driver**

4. Click Next.

5. Place a check in the box next to “CD-ROM drive” as shown in Figure 2-4.

![Add New Hardware Wizard](image2)

**Figure 2-4: Search the CD-ROM**
6. Click Next.

Windows 98 will locate the WmUSBEz.inf file that is on the CD-ROM as shown in Figure 2-5.

![Add New Hardware Wizard](image)

**Figure 2-5: The driver is located**

7. Click Next.

Figure 2-6 will appear.

![Copying Files...](image)

**Figure 2-6: Search for .sys File Dialog Box**

8. Click the Browse button.
Figure 2-7 will appear.

9. In Drives select your CD-ROM drive.
10. Click OK.

Figure 2-8 will appear.

11. Click OK.
The driver installation is now complete as shown in Figure 2-9.

Figure 2-9: Finish the Software Installation

12. Click Finish to exit the wizard.

Verify the installation by following the instructions in section 2.4.6.
2.4.5.2 Windows 2000 USB Driver Installation

Before using the ADSP-21161N EZ-KIT Lite for the first time, the Windows 2000 driver must first be installed. This is accomplished as follows:

1. Insert the EZ-KIT Lite CD-ROM into the CD-ROM drive.

The connection of the device to the USB port will activate the Windows 2000 “Found New Hardware Wizard” as shown in Figure 2-10.

![Figure 2-10: Found New Hardware Wizard](image)

2. Click Next.
3. Select “Search for a suitable driver for my device” as shown in Figure 2-11.

4. Click Next.
5. Make sure there is a check in the box next to “CD-ROM drive” as shown in Figure 2-12.

![Figure 2-12: Locate Driver Files](image)

6. Click Next.
Figure 2-13 appears.

Figure 2-13: Driver File Search Results

7. Click Next.
Windows 2000 will automatically install the ADSP-21161N EZ-KIT Lite driver. The driver installation is now complete as shown in Figure 2-14.

![Figure 2-14: Completing Driver Installation Dialog Box](image)

8. Click Finish to exit the wizard.

Verify the installation by following the instructions in section 2.4.6.

### 2.4.6 Driver Installation Verification

Before you use the EZ-KIT Lite evaluation system, verify that the USB driver software is installed properly:

1. Ensure that the USB cable is connected to the evaluation board and the PC.
2. Press and release the RESET button (SW8) on the evaluation board.
3. Verify that the red DSP RESET LED (LED8) stays lit for about 15 seconds.
4. After the DSP RESET LED (LED8) goes out, verify that the yellow USB monitor LED (LED10) is lit. This signifies that the board is communicating properly with the host PC, and is ready to run VisualDSP++.
2.4.7 Starting VisualDSP++

In order to start debugging, you must set up a session in VisualDSP++.

1. Hold down the Control (CTRL) key.
2. Select the Start button on the Windows taskbar, and then choose Programs, VisualDSP, VisualDSP++.

The Session List dialog box appears if you already have existing sessions. Skip to step 4 if this is the first time running VisualDSP++.

3. Click on New Session.
4. The New Selection dialog will appear as shown in Figure 2-15.

![New Session Dialog Box](image)

**Figure 2-15: New Session Dialog Box**

5. In Debug Target, choose “EZ-KIT Lite (ADSP-21161N)”.
6. Type a new target name in Session Name or accept the default name.
7. Click OK to return to the Session List. Highlight the new session and click Activate.
3 USING THE EZ-KIT LITE

3.1 Overview

This chapter provides specific information to assist you with developing programs for the ADSP-21161N EZ-KIT Lite board. This information appears in the following sections:

- **EZ-KIT Lite License Restrictions** (Section 3.2)
  Describes the restrictions of the EZ-KIT Lite license.

- **Memory Map** (Section 3.3)
  Defines the memory map to assist in developing programs for the EZ-KIT Lite evaluation system.

- **Using the SDRAM Interface** (Section 3.4)
  Defines the registers necessary for configuring external memory.

- **Using the Flag Pins** (Section 3.5)
  Describes how to use the programmable flag pins to assist in developing programs for the EZ-KIT Lite evaluation system.

- **Using the Interrupt Pins** (Section 3.6)
  Describes how to use the interrupt pins to assist in developing programs for the EZ-KIT Lite evaluation system.

- **Using the Audio Interface** (Section 3.7)
  Describes how to use the audio interface to assist in developing programs for the EZ-KIT Lite evaluation system.

- **Example Programs** (Section 3.8)
  Provides information about the example programs included in the ADSP-21161N EZ-KIT Lite evaluation system.

- **Using the Flash Programmer Utility** (Section 3.9)
  Provides information on the flash programmer utility included with VisualDSP++.

For more detailed information about programming the ADSP-21161N, see the documents referred to in section 1.6.
3.2 EZ-KIT Lite License Restrictions

The license that is shipped with the EZ-KIT Lite imposes the following restrictions:

- Program Memory (PM) space is limited to 5K words (1/4 of the ADSP-21161N PM space)
- No connections to Simulator or Emulator sessions are allowed.
- Only one EZ-KIT Lite can be connected to the host PC and debugged at a time

3.3 Memory Map

The ADSP-21161N has 1Mbit of internal SRAM that can be used for program storage or data storage. The configuration of internal SRAM is detailed in the ADSP-21161N DSP Hardware Reference.

The ADSP-21161N EZ-KIT Lite board contains 512K x 8-bits of external flash memory. This memory is connected to the DSP’s ~MS1 and ~BMS memory select pins. The flash memory can be accessed in either the boot memory space or the external memory space. The external memory interface is also connected to 1M x 48-bit SDRAM memory. This memory is connected to the ~MS0 pin.
### Table 3-1: EZ-KIT Lite Evaluation Board Memory Map

| Start Address | End Address | Content |
|---------------|-------------|---------|
| 0x0000 0000   | 0x0001 FFFF | IOP Registers (Internal) |
| 0x0002 0000   | 0x0002 1FFF | Block 0 Long Word Addressing |
| 0x0002 8000   | 0x0002 9FFF | Block 1 Long Word Addressing |
| 0x0004 0000   | 0x0004 3FFF | Block 0 Normal Word Addressing |
| 0x0005 0000   | 0x0005 3FFF | Block 1 Normal Word Addressing |
| 0x0008 0000   | 0x0008 7FFF | Block 0 Short Word Addressing |
| 0x000A 0000   | 0x000A 7FFF | Block 1 Short Word Addressing |
| 0x0010 0000   | 0x001F FFFF | Multi-processor Memory Space |
| 0x0020 0000   | 0x002F FFFF | External Memory Space Bank 0 (SDRAM) |
| 0x0400 0000   | 0x047F FFFF | External Memory Space Bank 1 (FLASH) |
| 0x0800 0000   | 0xBFF FFFF  | External Memory Space Bank 2 |
| 0x0C00 0000   | 0xFFF FFFF  | External Memory Space Bank 3 |

### 3.4 Using the SDRAM Interface

In order to use the SDRAM memory the two SDRAM control registers need to be set to the following values: SDRDIV = 0x1000 and SDCTL = 0x02014231

The SDCTL register configures the SDRAM controller for the following settings: (1/2 CCLK, no SDRAM buffering option, 2 SDRAM banks, SDRAM mapped to bank 0 only, no self-refresh, page size 256 words, SDRAM powerup mode is prechrg, 8 CRB refs, and then mode reg set cmd, tRCD = 2 cycles, tRP=2 cycles, tRAS=3 cycles, SDCL=1 cycle, and SDCLK0, SDCLK1, RAS, CAS and SDCLKE activated)

The SDRAM registers are configured automatically through the debugger. Checking the appropriate box as shown in Figure 3-1 disable this setting and allows manual configuration.
3.5 Using the Flag Pins

The ADSP-21161N has 12 asynchronous Flags I/O pins. 10 of these pins (FLAG0-9) are available to let you interact with the running program.

After the DSP is reset, the flags are configured as inputs. The directions of the flags are configured though the MODE2 register and are set and read though the FLAGS register. For more information on configuring the flag pins, see the ADSP-21161N DSP Hardware Reference. Flags and their uses are described in Table 3-2.

Table 3-2: Flag Pin Summary

| Flag     | Connected to | Use                                                                 |
|----------|--------------|----------------------------------------------------------------------|
| FLAG0    | SW1          | FLAG0-3 are connected to the push buttons to supply feedback for program execution. For instance, you can write your code to trigger a flag when a routine is complete. |
| FLAG1    | SW2          |                                                                      |
| FLAG2    | SW3          |                                                                      |
| FLAG3    | SW4          |                                                                      |
| FLAG4-   | LED2-LED7    | FLAG4-9 are connected to LEDs on the EZ-KIT Lite board and are for user output. |
| FLAG9    |              |                                                                      |
| FLAG10 & 11 | Not Connected | Not Available                                                        |

 Note: FLAG0 – FLAG3 are available on connector P10.
3.6 Using the Interrupt Pins

The ADSP-21161N has 3 interrupt pins (IRQ0-2) that let you interact with the running program. Each of the three external interrupts are directly accessible through the push button switches SW5 - SW7 on the EZ-KIT Lite board. For more information on configuring the interrupt pins, see the *ADSP-21161N DSP Hardware Reference*. Interrupts and their uses are described in Table 3-3.

Table 3-3: Interrupt Pin Summary

| Interrupt | Connected to | Use |
|-----------|--------------|-----|
| IRQ0      | SW5          | IRQ0-2 are connected to the push buttons and supply feedback for program execution. For instance, you can write your code to trigger a flag when a routine is complete. |
| IRQ1      | SW6          |     |
| IRQ2      | SW7          |     |

 Note: IRQ0 – IRQ3 are available on connector P10.

3.7 Using the Audio Interface

The audio interface on the EZ-KIT Lite board allows you to interface to the codec and digital receiver through various connectors. See section 4.5.2 for more information about the connectors. The audio interface consists of three main ICs, an AD1836, AD1852 and a CS8414.

The AD1836 multi-channel codec features six digital-to-analog converters (DACs) and four analog-to-digital converters (ADCs), support multiple digital stereo channels with 24-bit conversion resolution and a 96 kHz sample rate. The AD1836 features a 108 dB dynamic range for each of its six DACs, and a 104 dB dynamic range for its four ADCs.

The AD1852 is a complete 18/20/24-bit single-chip stereo digital audio playback system. It is comprised of a multibit sigma-delta modulator, digital interpolation filters, and analog output drive circuitry. Other features include an on-chip stereo attenuator and mute, programmed through an SPI-compatible serial control port. The AD1852 is fully compatible with all known DVD formats including 192kHz and 96kHz sample frequencies and 24-bits. It also is backwards compatible by supporting 50/15µs digital de-emphasis intended for "redbook" Compact Discs, as well as de-emphasis at 32kHz and 48kHz sample rate.

The CS8414 is a monolithic CMOS device that receives and decodes audio data up to 96kHz according to the AES/EBU, IEC958, S/PDIF, and EIAJ CP340/1201 interface standards. The CS8414 receives data from a transmission line, recovers the clock and synchronization signals, and de-multiplexes the audio and digital data. The CS8414 is setup to operate in I²S compatible mode.
The Microphone and Line-In jacks connect to the left and right ADC1 channel on the AD1836, depending on the setting of jumpers. See sections 4.3.9 and 4.3.8 for more information about configuring the jumpers. Two RCA jacks connect to ADC2 on the AD1836. This input is configured though the input mode selection jumpers see section 4.3.7 for more information.

The Line-Out jacks connect to the left and right DAC outputs of the AD1836 and AD1852.

The CS8414 has an error flag (VERF) that is used to indicate that the audio output may not be valid. This signal is connected to an LED (LED9) on the board. This signal may also be used by interpolation filters to provide error correction.

3.8 Example Programs

Example programs are provided with the ADSP-21161N EZ-KIT Lite to demonstrate various capabilities of the evaluation board. These programs are installed with the EZ-KIT Lite software and can be found in \...\VisualDSP\211xx\EZ-KITs\ADSP-21161N\Examples. Please refer to the example program readme files for more information.

3.9 Using the Flash Programmer Utility

The ADSP-21161N EZ-KIT Lite evaluation system includes a flash programmer utility. The utility allows you to program the flash on the EZ-KIT Lite. This utility must be installed separately from the debug software. To install the utility, insert the EZ-KIT Lite CD-ROM and follow the steps in the installation wizard.

For more information on the flash programmer utility, from the start menu choose Programs\VisualDSP\Flash Programmer Help.
4 EZ-KIT LITE HARDWARE REFERENCE

4.1 Overview

This chapter describes the hardware design of the ADSP-21161N EZ-KIT Lite board. The following topics are covered:

- **System Architecture** (Section 4.2)
  Describes the configuration of the DSP as well as a description of how all of the components on the board interface with the DSP.

- **Jumper Settings** (Section 4.3)
  Shows the location and describes the function of all the configuration jumpers.

- **LEDs and Push Buttons** (Section 4.4)
  Shows the location and describes the function of all the LEDs and push buttons.

- **Connectors** (Section 4.5)
  Shows the location and gives the part number for all of the connectors on the board. Also, the manufacturer and part number information is given for the mating part.

- **Specifications** (Section 4.6)
  Gives the requirements for powering the board as well as the mechanical locations of some components of the board.
4.2 System Architecture

The EZ-KIT Lite has been designed to demonstrate the capabilities of the ADSP-21161N DSP. This section will describe the DSP’s configuration on the EZ-KIT Lite board.

![Figure 4-1: System Architecture](image)

The DSP core voltage is 1.8V and the external interface operates at 3.3V.

A 12.5MHz through-hole oscillator supplies the input clock to the DSP. Footprints are provided on the board for a surface-mount oscillator and a through-hole crystal for alternate user installed clocks. The speed at which the core operates is determined by the location of the Clock Mode jumpers (JP21). (See section 4.3.12.) By default, the DSP core runs at 100MHz.
4.2.1 External Port

The external port is connected to a 512K x 8-bit flash memory. This memory is connected to the boot memory select (~BMS) pin and the memory select 1 (~MS1) pin, allowing the flash memory to be used to boot the DSP as well as store information during normal operation. Refer to section 3.3 for information about the location of the flash memory in the DSP’s memory map.

The external memory interface is also connected to 1M x 48-bit SDRAM memory. This memory is connected to the memory select 0 (~MS0) pin. Refer to section 4.3.1 for information about configuring the width of the SDRAM. Refer to section 3.3 for information about the location of the flash memory in the DSP’s memory map.

Some of the address, data, and control signals are available externally via two off-board connectors. The pinout of the EP connectors (P9 and P10) can be found in APPENDIX B: SCHEMATIC.

4.2.2 Host Processor Interface (HPI)

The Host Port Interface (HPI) signals are brought to an unpopulated off board connector P9. This allows the HPI to interface to a user application. The pinout of the host port connector (P9) can be found in APPENDIX B: SCHEMATIC.

4.2.3 SPORT0 and SPORT2 – Audio Interface

SPORT0 and SPORT2 are connected to the AD1836 codec (U10). A 3.5mm stereo jack and four RCA mono jacks allow audio to be input. A 3.5mm stereo jack and eight RCA mono jacks allow audio to be output.

The codec contains two input channels. One channel is connected to a 3.5mm stereo jack and two RCA jacks. The 3.5mm stereo jack can be connected to a microphone. The two RCA jacks can be connected to a line out from an audio device. You can supply an audio input to the codec microphone input channel (MIC1) or to the LINE_IN input channel. The jumper settings of JP1 determine the codec channel driven by the input jack (P3).

4.2.4 SPI - Audio Interface

The SPI is connected to the AD1836 and AD1852. This is used for writing and reading from control registers on the devices.
4.2.5 Breadboard Area

Use the breadboard area to add external circuitry.

- All board voltages and grounds
- Package Footprints
  - 1x SOIC16
  - 1x SOIC20
  - 4x SOT23-6
  - 1x PSOP44
  - 2x SOT23
  - 27x 0805

➢ Warning: Any circuitry added to the breadboard area is not supported.

4.2.6 JTAG Emulation Port

The JTAG emulation port allows an emulator to access the DSP’s internal and external memory, as well as the special function registers through a 14-pin header. See section 4.5.5 for more information about the JTAG connector. To learn more about available emulators, contact Analog Devices (See section 1.1).

4.3 Jumper Settings

This section describes the function of all the jumpers. The following figure shows the location of all the jumpers.
4.3.1 SDRAM Disable (JP1)

JP1 is used to enable or disable the third SDRAM device. When this jumper is installed, the ADSP-21161N can access the SDRAM as 48-bit wide external memory.

The upper 16 bits of data are multiplexed with the Link Ports and the external data bus. Therefore when the jumper is installed the Link Ports are not available. To use the Link Ports this jumper must be removed.
4.3.2 SPDIF Selection Jumper (JP2)

JP2 is used to select the SPDIF input to the CS8414 Digital Audio Receiver. When the jumper is configured for an optical connection, the TOSLINK optical input connector (P4) should be used. When the jumper is configured for a coax connection, the RCA input connector (P5) should be used.

Table 4-1: SPDIF Modes

| Jumper Location | Mode                  |
|-----------------|-----------------------|
| 1 & 2           | Optical (factory default) |
| 2 & 3           | Coax                  |

4.3.3 MCLK Selection Jumper (JP3)

JP3 is used to select the MCLK source for the AD1836 and AD1852.

Table 4-2: MCLK Selection

| Jumper Location | MCLK Source                          |
|-----------------|--------------------------------------|
| 1 & 2           | Audio Oscillator (12.288 MHz) (factory default) |
| 2 & 3           | Derived clock from SPDIF Stream      |

4.3.4 FLAG0 Enable (JP4)

In standard configuration, FLAG1 is connected to the AD1836 and used as a select for the SPI port. This jumper should be removed to use the push button switch or the signal on the expansion connector (P10). Once this jumper is removed, the SPI can no longer communicate with the AD1836.

4.3.5 FLAG1 Enable (JP5)

In standard configuration, FLAG1 is connected to the AD1852 and used as a select for the SPI port. This jumper should be removed to use the push button switch or the signal on the expansion connector (P10). Once this jumper is removed, the SPI can no longer communicate with the AD1852.

4.3.6 Sample Frequency Jumper (JP6)

JP6 is used to select the sample frequency for the AD1852. Table 4-3 shows the valid modes that may be used.
Table 4-3: Sample Frequencies

| Jumper Location | Sample Frequency                      |
|-----------------|---------------------------------------|
| None installed  | Not Allowed                           |
| 3 & 4           | 192 kHz (2x Interpolator)             |
| 1 & 2           | 96 kHz (4x Interpolator)              |
| 1 & 2, 3 & 4    | 48 kHz (8x Interpolator) (factory default) |

4.3.7 ADC2 Input Mode Selection Jumper (JP7 and JP8)

JP7 and JP8 control the input mode to ADC2 on the AD1836. In high-performance mode, the signal is routed straight in to the ADC. In PGA mode, the signal goes through a multiplexer and a programmable gain amplifier inside of the codec.

Table 4-4: ADC Input Mode

| Jumper Location | Input Mode          |
|-----------------|---------------------|
| 3 & 5, 4 & 6    | PGA (factory default) |
| 1 & 3, 2 & 4    | High Performance    |

4.3.8 MIC Pre-Amp Gain Selection Jumpers (JP9 and JP10)

JP9 and JP10 are used to select the pre-amp gain for the microphone circuit. The gain for the left and right channel should be configured the same.

Table 4-5: MIC Pre Amp Gain

| Jumper Position | Gain            |
|-----------------|-----------------|
| Not Installed   | 0dB             |
| 1 & 2           | 20dB            |
| 2 & 3           | 40dB (factory default) |

4.3.9 ADC1 Input Selector Jumper (JP11)

JP11 is used to select the input source for ADC2. If the input source for ADC2 is Line-In then the RCA connector P6 should be used. If the input source for ADC2 is a microphone then the mini stereo plug P7 should be used. If a microphone is used, the gain of the circuit may be increased as described in the section 4.3.8.
When the JP11 jumpers are between pins 1 and 3 and between pins 2 and 4, the connection is to P7. When the jumpers are between pins 3 and 5 and between pins 4 and 6, P3 the connection is to P6. The jumper settings are illustrated below. (The words MIC and LINE are on the board to give a reference)

| Microphone Input | Stereo LINE_IN (DEFAULT) |
|------------------|--------------------------|
| ![MIC](image1)   | ![MIC](image2)           |
| ![LINE](image3)  | ![LINE](image4)          |

**Figure 4-3: Audio Input Jumper Settings**

### 4.3.10 Processor ID Jumpers (JP19)

JP19 is used to select different a different processor ID for the DSP. During typical operation of the EZ-KIT Lite board, there is only a single DSP in the system. The jumper should be set to the single processor setting. In the case where a second processor is attached to the board though the link port these jumpers should be changed to configure one board for processor 1 and the other board for processor 2. System configuration options are shown in Table 4-6.

#### Table 4-6: Processor ID Modes

| Jumper Position | Description            |
|-----------------|------------------------|
| 1 & 2, 3 & 4, 5 & 6 | Single Processor (Default) |
| 3 & 4, 5 & 6     | Processor 1            |
| 1 & 2, 5 & 6     | Processor 2            |
| Other            | INVALID                |

### 4.3.11 Boot Mode Select (JP20)

JP20 determines how the DSP will boot. Table 4-7 shows the jumper setting for the boot modes.
Table 4-7: Boot Mode Select Jumper (JP20) Settings

| EBOOT Pins 1 & 2 | LBOOT Pins 3 & 4 | BMS Pins 5 & 6 | Boot Mode                  |
|------------------|------------------|----------------|----------------------------|
| Not Installed    | Installed        | Not Installed (Output) | EPROM BOOT(DEFAULT)       |
| Installed        | Installed        | Not Installed (Input)   | Host Processor Boot        |
| Installed        | Not Installed    | Installed (Input)       | Serial Boot via SPI        |
| Installed        | Not Installed    | Not Installed (Input)   | Link Port Boot             |
| Installed        | Installed        | Installed (Input)       | No Boot                    |
| Not Installed    | Not Installed    | Installed (Input)       | Reserved                   |

4.3.12 Clock Mode Jumpers (JP21)

JP21 controls the speed for the core and external port of the ADSP-21161N. The frequency supplied to CLKIN of the DSP may be changed by removing the 12.5 MHz oscillator (U24) that is shipped with the board and replacing it with a different oscillator or crystal (Y2). A clock mode and frequency should be selected so that the min and max specs of the ADSP-21161N are not exceeded. For more information on clock modes, see the ADSP-21161N DSP Hardware Reference. Table 4-8 shows the jumper setting for the clock modes.

Table 4-8: Clock Mode Selections

| CLKDBL Pins 1 & 2 | CLK_CFG1 Pins 3 & 4 | CLK_CFG0 Pins 5 & 6 | Core Clock Ratio | EP Clock Ratio |
|-------------------|---------------------|---------------------|------------------|----------------|
| Not Installed     | Installed           | Installed           | 2:1              | 1x             |
| Not Installed     | Installed           | Not Installed       | 3:1              | 1x             |
| Not Installed     | Not Installed       | Installed           | 4:1              | 1x             |
| Installed         | Installed           | Installed           | 4:1              | 2x             |
| Installed         | Installed           | Not Installed       | 6:1              | 2x             |
| Installed         | Not Installed       | Installed           | **8:1**          | **2x (Default)** |
4.3.13 BMS Enable (JP22)

JP22 is used to control the routing of the Boot Memory Select (BMS) signal. When the jumper is installed the BMS signal is routed to the FLASH memory interface and can be used for reading, writing and booting. The jumper should be installed when using EPROM boot mode. This jumper should be removed when using the serial boot or no boot mode. If the jumper was left on in these modes the flash would always be selected because the BMS signal is grounded in these modes.

4.4 LEDs and Push Buttons

This section describes the function of all the LEDs and push buttons. Figure 4-4 shows the location of all the LEDs and push buttons.
4.4.1 Reset LEDs (LED1, LED8)

When LED1 is lit, it indicates that the master reset of all the major ICs is active.

When LED8 is lit, the ADSP-21161N (U1) is being reset. The USB interface resets the ADSP-21161N during USB communication initialization.
4.4.2 FLAG LEDs (LED2 - LED7)

The FLAG LEDs connect to the DSP’s flag pins (FLAG4-FLAG9). These LEDs are active HIGH and are lit by an output of “1” from the DSP. Refer to section 3.4 for more information about the use of the programmable flags when programming the DSP. Table 4-9 shows the FLAG signal and the corresponding LED.

Table 4-9: FLAG LEDs

| FLAG Pin | LED Reference Designator |
|----------|--------------------------|
| FLAG4    | LED7                     |
| FLAG5    | LED6                     |
| FLAG6    | LED5                     |
| FLAG7    | LED4                     |
| FLAG8    | LED3                     |
| FLAG9    | LED2                     |

4.4.3 VERF LED (LED9)

The VERF LED indicates that there is a possible error on the audio stream of the CS8414 digital receiver. One cause for this is that there are no digital audio cables connected to the optical or coaxial SPDIF connectors.

4.4.4 USB Monitor LED (LED10)

The USB Monitor LED indicates that USB communication has been initialized successfully and you may now connect to the DSP using VisualDSP++. If the LED is not lit, try resetting the board, and/or reinstalling the USB driver (see section 2.4.5).

4.4.5 Power LED (LED11)

LED11 is a green LED that indicates that power is being properly supplied to the board.
4.4.6 Programmable Flag Push Buttons (SW1 – SW4)

Four push buttons are provided for general-purpose user input. SW1 - 4 connect to the DSP’s programmable flag pins. The push buttons are active high and when pressed send a high (1) to the DSP. Refer to section 3.4 for more information about the use of the programmable flags when programming the DSP. Table 4-10 shows the FLAG signal and the corresponding switch.

Table 4-10: FLAG Switches

| Flag Pin | Push Button Reference Designator |
|----------|----------------------------------|
| FLAG0    | SW1                              |
| FLAG1    | SW2                              |
| FLAG2    | SW3                              |
| FLAG3    | SW4                              |

4.4.7 Interrupt Push Buttons (SW5 – SW7)

Three push buttons are provided for general-purpose user input. SW5 - 7 connect to the DSP’s programmable flag pins. The push buttons are active high and when pressed send a high (1) to the DSP. Refer to section 3.4 for more information about the use of the programmable flags when programming the DSP. Table 4-11 shows the interrupt signal and the corresponding switch.

Table 4-11: Interrupt Switches

| Flag Pin | Push Button Reference Designator |
|----------|----------------------------------|
| IRQ0     | SW5                              |
| IRQ1     | SW6                              |
| IRQ2     | SW7                              |

4.4.8 Reset Push Button (SW8)

The RESET push button resets all of the IC’s on the board. During reset, the USB interface is automatically reinitialized.

➢ Warning: Pressing the RESET push button (SW8) while VisualDSP++ is running disrupts communication and causes errors in the current debug session. VisualDSP++ must be closed and re-opened.
4.5 Connectors

This section describes the function of the connectors and gives information about mating connectors. The following figure shows the locations of the connectors.

![Connector Locations](image)

**Figure 4-5: Connector Locations**

### 4.5.1 USB (P2)

The USB connector is a standard Type B USB receptacle.

| Part Description          | Manufacturer | Part Number |
|---------------------------|--------------|-------------|
| Type B USB receptacle     | Mill-Max     | 897-30-004-90-000 |
|                           | Digi-Key     | ED90003-ND  |

**Mating Connector**

| USB cable (provided with kit) | Assmann | AK672-5 |
|-------------------------------|---------|---------|
|                               | Digi-Key| AK672-5ND |

### 4.5.2 Audio (P4 – P8, P17)

There are 2 3.5mm Stereo audio jacks, 13 RCA jacks and 1 optical connector.
| Part Description                                      | Manufacturer   | Part Number |
|------------------------------------------------------|----------------|-------------|
| 3.5mm stereo jack (P7 & P16)                         | Shogyo         | SJ-0359AM-5 |
| RCA Jacks (P6)                                       | SWITCHCRAFT    | PJRAS2X2S01 |
| RCA Jacks (P8)                                       | SWITCHCRAFT    | PJRAS4X2U01 |
| TORX (P4)                                            | TOSHIBA        | TORX173     |
| Coaxial (P5)                                         | SWITCHCRAFT    | PJRAN1X1U01 |

**Mating Connector**

| Part Description                                      | Manufacturer   | Part Number |
|------------------------------------------------------|----------------|-------------|
| 3.5mm stereo plug to 3.5mm stereo cable (P7 & P16)   | Radio Shack    | L12-2397A   |
| Two channel RCA interconnect cable (P6 & P8)         | Monster Cable  | BI100-1M    |
| Digital Fiber-Optic Cable (P4)                       | Monster Cable  | ILS100-1M   |
| Digital Coaxial Cable (P5)                           | Monster Cable  | IDL100-1M   |

### 4.5.3 External port and Host Processor Interface (P9, and P10)

Two MICTOR board-to-board connectors provide all of the DSP’s External Port signals. Contact AMP for information about mating connectors.

| Part Description | Manufacturer | Part Number |
|------------------|--------------|-------------|
| 38 Position MICTOR | AMP          | 2-767004-2  |

### 4.5.4 JTAG (P12)

The JTAG header is the connecting point for a JTAG in-circuit emulator pod. **Note:** Pin 3 is missing to provide keying. Pin 3 in the mating connector should have a plug.

When an emulator is connected to the JTAG header, the USB debug interface is disabled.

> **WARNING:** When using an emulator with the EZ-KIT Lite board, follow the connection instructions provided with the emulator.

### 4.5.5 Link Ports (P13 and P14)

Each link port is connected to a 26-pin connector. Refer to EE-106 for more information about the link port connectors.
### 4.5.6 SPORT1 and SPORT3 (P15)

SPORT1 and SPORT3 are connected to a 20-pin connector.

| Part Description                  | Manufacturer | Part Number |
|-----------------------------------|--------------|-------------|
| 20 position AMPMODU system        | AMP          | 104069-1    |
| 50 receptacle                     |              |             |

**Mating Connector**

| Part Description                  | Manufacturer | Part Number |
|-----------------------------------|--------------|-------------|
| 20 position AMPMODU system        | AMP          | 2-487937-0  |
| 20 connector                      |              |             |
| 20 position AMPMODU system        | AMP          | 2-487938-0  |
| 20 connector (w/o lock)           |              |             |
| Flexible film contacts (20 per   | AMP          | 487547-1    |
| connector)                        |              |             |

### 4.5.7 Power Connector (P16)

The power connector provides all of the power necessary to operate the EZ-KIT Lite board.

| Part Description                  | Manufacturer | Part Number |
|-----------------------------------|--------------|-------------|
| 2.5mm Power Jack                  | Switchcraft  | RAPC712     |
|                                   | Digi-key     | SC1152-ND   |

**Mating Power Supply (shipped with EZ-KIT Lite)**

| Part Description                  | Manufacturer | Part Number |
|-----------------------------------|--------------|-------------|
| 7.5v Power Supply                 | GlobTek      | TR9CC2000LCP-Y |

### 4.6 Specifications

This section provides the requirements for powering the board.

#### 4.6.1 Power Supply

The power connector supplies DC power to the EZ-KIT Lite board. Table 4-12 shows the power connector pinout.
Table 4-12: Power Connector

| Terminal   | Connection     |
|------------|----------------|
| Center pin | +7.5 VDC@2amps |
| Outer Ring | GND            |

4.6.2 Board Current Measurements

The ADSP-21161N EZ-KIT Lite board provides two zero-ohm resistors that may be removed to measure current draw. Table 4-13 shows the resistor number, the voltage plane, and a description of the components on the plane.

Table 4-13: Current Measurement Resistors

| Resistor | Voltage Plane | Description          |
|----------|---------------|----------------------|
| R168     | VDDINT        | Core Voltage of the DSP |
| R169     | VDDEXT        | I/O Voltage of the DSP |
## APPENDIX A: BILL OF MATERIALS

| Item | Qty | Description                        | Reference Designator | Manufacturer     | Part Number          |
|------|-----|------------------------------------|----------------------|------------------|----------------------|
| 1    | 1   | FLASH-512K-X-8                     | U5                   | ST MICRO         | M29W040B120K6        |
| 2    | 2   | HEX-INVER-SCHMITT-TRIGGER          | U21-22               | PHILIPS          | 74LVC14AD            |
| 3    | 3   | 1MX16-SDRAM-143MHZ                 | U2-4                 | MICRON           | MT48LC1M16A1TG-7S    |
| 4    | 1   | 96KHZ-DIGITAL-AUDIO-RECVR          | U8                   | CIRRUS LOGIC     | CS8414-CS            |
| 5    | 1   | USB-TX/RX MICROCONTROLLER          | U6                   | CYPRESS          | CY7C64603-128NC03-A  |
| 6    | 1   | NPN TRANSISTOR 1A                  | Q2                   | FAIRCHILD        | MMBT4124             |
| 7    | 1   | NPN TRANSISTOR 200MA               | Q1                   | FAIRCHILD        | MMBT4401             |
| 8    | 1   | CRYSTAL OSCILLATOR                 | Y1                   | DIGIKEY          | SE2507CT-ND          |
| 9    | 2   | NAND GATE                          | U9,U27               | PHILIPS          | 74LVC00AD            |
| 10   | 1   | 128 BIT SERIAL EEPROM              | U7                   | MICROCHIP        | 24LC00-SN            |
| 11   | 1   | ADJ 200MA REGULATOR                | VR4                  | ANALOG DEVICES   | ADP3331ART           |
| 12   | 1   | 128K X 8 SRAM                      | U30                  | CYPRESS          | CY7C1019V33-15VC     |
| 13   | 1   | DUAL AMP 250MA                     | U29                  | ANALOG DEVICES   | AD8532AR             |
| 14   | 1   | OSCILLATOR                         | U25                  | DIGI01           | SG-8002DC-PCC-ND     |
|      |     |                                    |                      |                  | 12.288MH             |
| 15   | 2   | SINGLE-2 INPUT-NOR                 | U34,U37              | TI               | SN74AHC1G02DBVR      |
| 16   | 1   | 8-BIT-PARALLEL-SERIAL              | U33                  | TI               | SN74LV164AD          |
| 17   | 1   | 64-BYTE-FIFO                       | U32                  | CYPRESS          | CY7C4201V-15AC       |
| 18   | 1   | 12.5 MHz OSC                       | U24                  | DIGI-KEY         | SG-8002DC-PCC-ND     |
| 19   | 2   | 1000 PF CAP                        | C85-86               | AVX              | 12065A102JAT2A       |
| 20   | 8   | 2200 PF CAP                        | C40,C46,C52,C58,C64,C70,C76,C82 | AVX | 12065A222JAT2A |
| 21   | 1   | VOLTAGE-SUPERVISOR                 | U26                  | ANALOG           | ADM708SAR            |
| 22   | 1   | MULTIBIT-SIGMA-DELTA-DAC           | U11                  | ADI              | AD1852JRS            |
| 23   | 1   | MULTI-CHANNEL-96KHZ-CODEC          | U10                  | ADI              | AD1836AS             |
| 24   | 1   | 1MM SPACING                        | U1                   | ADI              | ADSP-21161N-100      |
| 25   | 1   | 3.3V-1.0AMP REGULATOR              | VR2                  | ANALOG           | ADP3338ARM-3.3       |
| 26   | 2   | 5V-1.5A REGULATOR                  | VR1,VR5              | ANALOG           | ADP3339AKC-5-REEL    |
| 27   | 10  | DUAL AUDIO OP AMP                  | U12-20,U28           | ANALOG           | SSM2275S             |
| Item | Qty | Description          | Reference Designator | Manufacturer   | Part Number       |
|------|-----|----------------------|----------------------|---------------|-------------------|
| 28   | 3   | TANT CAP             | CT23-25              | AVX           | TAJC475K025R      |
| 29   | 1   | POWER JACK           | P16                  | SWITCHCRAFT   | SC1152-ND12       |
| 30   | 1   | USB CONNECTOR        | P2                   | MILL-MAX      | 897-30-004-90-000000 |
| 31   | 1   | FIBER OPTIC REV MODULE | P4                  | TOSHIBA       | TORX173           |
| 32   | 1   | RCA 4X2              | P8                   | SWITCHCRAFT   | PJRAS4X2U01       |
| 33   | 1   | RCA 1X1              | P5                   | SWITCHCRAFT   | PJRAN1X1U01       |
| 34   | 1   | RCA 2X2              | P6                   | SWITCHCRAFT   | PJRAS2X2S01       |
| 35   | 2   | LNKPR 12X2           | P13-14               | HONDA(TSUSHINK) | RMCA-EA26LMY-0M03-A |
| 36   | 1   | .05 10X2             | P15                  | AMP           | 104069-1          |
| 37   | 8   | 6MM PUSH BUTTON      | SW1-8                | PANASONIC     | EVQ-PAD04M        |
| 38   | 1   | 10 1/8W 5% 1206      | R2                   | PANASONIC     | P10ECT-ND         |
| 39   | 6   | 0.00 1/8W 5% 1206    | R153,R154,R168-169,R217,R218 | YAGEO | P0.0ETR           |
| 40   | 8   | AMBER LED            | LED2-7,LED9-10       | PANASONIC     | LN1461C-TR        |
| 41   | 8   | 330pF 50V 5% 805     | C36,C42,C48,C54,C60,C66,C72,C78 | AVX | 08055A331JAT      |
| 42   | 80  | 0.01uF 100V 10% 805  | C2,C6-7,C91-149,C154-155,C165-171,C184-C186,C174-179 | AVX | 08051C103KAT2A    |
| 43   | 11  | 0.22uF 25V 10% 805   | C156-164,C172,C183   | AVX           | 08053C224FAT      |
| 44   | 15  | 0.1uF 50V 10% 805    | C1,C5,C9-11,C33,C87-90,C150-153,C173 | AVX | 08055C104KAT      |
| 45   | 8   | 0.001uF 50V 5% 805   | C14-15,C19-20,C24-25,C29-30 | AVX | 08055A102JAT2A    |
| 46   | 5   | 10uF 16V 10% C       | CT19-22,CT36         | AVX           | TAJC106K016R      |
| 47   | 4   | 33 100MW 5% 805      | R1,R150,R176,R152    | AVX           | CR21-330JTR       |
| 48   | 4   | 4.7K 100MW 5% 805    | R184,R188,R189,R191  | AVX           | CR21-4701F-T      |
| 49   | 11  | 680 100MW 5% 805     | R137-147             | AVX           | CR21-6800F-T      |
| 50   | 1   | 1M 100MW 5% 805      | R12                  | AVX           | CR21-1004F-T      |
| 51   | 1   | 475 100MW 5% 805     | R16                  | AVX           | CR21-471J-T       |
| 52   | 1   | 1.5K 100MW 5% 805    | R7                   | AVX           | CR21-1501F-T      |
| 53   | 2   | 2.00K 1/8W 1% 1206   | R49-50               | DALE          | CRCW1206-2001FRT1 |
| 54   | 10  | 49.9K 1/8W 1% 1206   | R66,R74,R82,R90,R98,R106,R114,R122,R192,R206 | AVX | CR32-4992F-T      |
| 55   | 2   | 2.21K 1/8W 1% 1206   | R10-11               | AVX           | CR32-2211F-T      |
| Item | Qty | Description       | Reference Designator | Manufacturer | Part Number |
|------|-----|-------------------|----------------------|--------------|-------------|
| 56   | 24  | 100pF 100V 5% 1206| C12,C16-17,C21-22,C26-27,C31,C35,C38 | AVX          | 12061A101JAT2A |
| 57   | 24  | 100pF 100V 5% 1206| C41,C44,C47,C50,C53,C56,C59,C62,C65,C68, | AVX          | 12061A101JAT2A |
| 58   | 24  | 100pF 100V 5% 1206| C71,C74,C80,C77,     | AVX          | 12061A101JAT2A |
| 59   | 5   | 10uF 16V 10% B    | CT1-4,CT11           | AVX          | TAJB106K016R |
| 60   | 7   | 100 100MW 5% 805  | R123,R125,R127,R129,R131,R133,R135 | AVX          | CR21-101J-T  |
| 61   | 8   | 220pf 50V 10% 1206| C39,C45,C51,C57,C63,C69,C75,C81 | AVX          | 12061A221JAT2A |
| 62   | 1   | 0.06 CHOKE        | FER13                | MURATA       | PLM250S40T1  |
| 63   | 2   | SILICON RECTIFIER | D1-2                 | GENERALSEMI  | S2A          |
| 64   | 12  | 0.70 BEAD         | FER1-12              | STEWARD      | HZ1206B601R  |
| 65   | 8   | 237 1/8W 1% 1206  | R23,R27,R30,R34,R40-41,R47-48 | KOA          | RK73H2BT2370F |
| 66   | 4   | 750K 1/8W 1% 1206 | R25,R32,R38,R45      | KOA          | RK73H2BT7503F |
| 67   | 16  | 5.76K 1/8W 1% 1206| R21,R22,R24,R26,R28-29,R31,R33,R35-37,R39,R42-44,R46 | DALE        | CRCW12065761FRT1 |
| 68   | 8   | 11.0K 1/8W 1% 1206| R59,R67,R75,R83,R91,R99,R107,R115 | DALE        | CRCW12061102FTR1 |
| 69   | 1   | 68NF 50V 10% 805  | C8                   | MURRATA      | GRM40X7R683K050AL |
| 70   | 8   | 120PF 50V 5% 1206 | C13,C18,C23,C28,C187-190 | PHILLIPS    | 1206CG121J9B200 |
| 71   | 1   | 75 1/8W 5% 1206   | R14                  | PHILIPS      | 9C12063A75R0JLRT/R |
| 72   | 2   | 820PF 100V 10% 1206| C32,C34              | AVX          | 12061A821KAT2A |
| 73   | 2   | 30PF 100V 5% 1206  | C3-4                 | AVX          | 12061A300JAT2A |
| 74   | 8   | 680PF 50V 1% 805  | C37,C43,C49,C55,C61,C67,C73,C79 | AVX        | 08055A681FAT2A |
| 75   | 8   | 2.74K 1/8W 1% 1206| R63,R71,R79,R87,R95,R103,R111,R119 | PANASONIC  | ERJ-8ENF2741V |
| 76   | 16  | 5.49K 1/8W 1% 1206| R60,R61,R68,R69,R76,R77,R84,R85,R92,R93,R100,R101,R108,R109,R116,R117 | PANASONIC | ERJ-8ENF5491V |
| 77   | 8   | 3.32K 1/8W 1% 1206| R62,R70,R78,R86,R94,R102,R110,R118 | PANASONIC | ERJ-8ENF3321V |
| 78   | 2   | 100 1/8W 1% 1206  | R54,R57              | PANASONIC    | ERJ-8ENF1000V |
| 79   | 8   | 1.65K 1/8W 1% 1206| R64,R72,R80,R88,R96,R104,R112,R120 | PANASONIC | ERJ-8ENF1651V |
| 80   | 6   | 10UF 16V 20%      | CT5-10               | DIGI-KEY     | PCE3062TR-ND |
| 81   | 10  | 68UF 25V 20%      | CT26-35              | PANASONIC    | EEV-FC1E680P |
| Item | Qty | Description               | Reference Designator | Manufacturer       | Part Number     |
|------|-----|--------------------------|----------------------|--------------------|-----------------|
| 82   | 1   | 365K 1/8W 1% 1206        | R215                 | DIGI-KEY           | P365KFCT-ND     |
| 83   | 1   | 634K 1/8W 1% 1206        | R214                 | DIGI-KEY           | P634KFCT-ND     |
| 84   | 1   | 2A SL22 DO-214AA         | D3                   | GENERAL SEMI       | SL22            |
| 85   | 2   | 10K 100MW 2% RNET16      | RN1-2                | CTS                | 767-161-103G    |
| 86   | 1   | 1K 1/8W 5% 1206          | R5                   | AVX                | CR32-102J-T     |
| 87   | 2   | 100K 1/8W 5% 1206        | R167,R213            | AVX                | CR32-103J-T     |
| 88   | 2   | 1.00K 1/8W 1% 1206       | R53,R56              | DALE               | CRCW1206-1001FRT1 |
| 89   | 2   | 20.0K 1/8W 1% 1206       | R170, R173           | DALE               | CRCW1206-2002FRT1 |
| 90   | 2   | 22 1/8W 5% 1206          | R8-9                 | AVX                | CR32-220J-T     |
| 91   | 1   | 74FCT244AT QSOP20        | U23                  | CYPRESS            | CY74FCT244ATQC  |
| 92   | 4   | 10.0K 1/8W 1% 1206       | R51-52,R55,R58       | DALE               | CRCW1206-1002FRT1 |
| 93   | 2   | RED-SMT                  | LED1,LED8            | PANASONIC          | LN1261C         |
| 94   | 1   | GREEN-SMT                | LED11                | PANASONIC          | LN1361C         |
| 95   | 8   | 604 1/8W 1% 1206         | R65,R73,R81,R89,R97,R105,R113,R121 | PANASONIC | ERJ-8ENF6040V |
| 96   | 7   | 1uF 25V 20% A            | CT12-18              | AVX                | TAJA105K035R    |
| 97   | 3   | QUICKSWITCH              | U31,U35,U36          | ANALOG DEV.        | ADG774ABRQ      |
| 98   | 6   | IDC 2X1                  | JP1,JP4-5,JP22-23,JP25 | BERG               | 54101-T08-02    |
| 99   | 4   | IDC 3X1                  | JP2-3,JP9-10         | BERG               | 54101-T08-03    |
| 100  | 1   | IDC 2X2                  | JP6                  | BERG               | 54102-T08-02    |
| 101  | 6   | IDC 3X2                  | JP7-8,JP11,JP19-21   | BERG               | 54102-T08-03    |
| 102  | 1   | IDC 7X2                  | P12                  | BERG               | 54102-T08-07    |
| 103  | 1   | 2.5A RESETABLE FUSE      | F1                   | RAYCHEM CORP.      | SMD250-2        |
| 104  | 2   | 3.5MM STEREO_JACK        | P7,P17               | SHOGYO             | SJ-0359AM-5     |
## INDEX

**A**

- AD1836 .................................................. 3-5
- AD1852 .................................................. 3-5
- ADC1 .................................................. 4-7
- ADC2 .................................................. 4-7
- Architecture ........................................... 4-2
- Audio .................................................. 4-14
- Audio Interface .... 3-5. See SPORT0 and SPORT2

**B**

- BMS Enable ........................................... 4-10
- Boot Mode Select .................................... 4-8
- Breadboard ........................................... 4-4

**C**

- Clock Mode ........................................... 4-9
- Clock Mode Jumpers ................................ 4-2
- Connectors ........................................... 4-14
  - P10 .................................................. 4-3
  - P11 .................................................. 4-3
  - P12 .................................................. 4-15
  - P12 .................................................. 4-3
  - P13 and P14 ....................................... 4-15
  - P15 .................................................. 4-16
  - P16 .................................................. 4-16
  - P17 .................................................. 4-14
  - P2 .................................................. 4-14
  - P3 .................................................. 4-3, 4-8
  - P4 – P8 ............................................. 4-14
  - P9 and P10 ......................................... 4-15
- Contents .............................................. 2-1
- Core Voltage .......................................... 4-2
- CS8414 .................................................. 3-5
- Current Measurements ............................. 4-17
- Customer Support ................................... 1-3

**D**

- Documents ........................................... 1-4, 1-6

**E**

- Example Programs ................................... 3-6
- External Port ......................................... 4-3, 4-15

**F**

- Features ............................................... 1-1
- FLAG0 .................................................. 4-6
- FLAG1 .................................................. 4-6
- Flags .................................................. 3-4
- Flash Memory ........................................ 3-2, 4-3
- Flash Programmer Utility ......................... 3-6

**H**

- Help, On-line ......................................... 1-4
- Host Processor Interface ......................... 4-3, 4-15

**I**

- Installation ........................................... 2-2, 2-10
  - Verification ....................................... 2-15
    - Windows 2000 USB Driver ............ 2-11
    - Windows 98 USB Driver ............... 2-6
- Interrupts ........................................... 3-5
- IO Voltage ........................................... 4-2

**J**

- JTAG .................................................. 4-4, 4-15
- Jumpers .............................................. 4-4
  - Default Settings ............................... 2-4, 2-5
  - JP1 .................................................. 4-3, 4-5, 4-8
  - JP11 .................................................. 4-7
  - JP19 .................................................. 4-8
  - JP2 .................................................. 4-6
  - JP20 .................................................. 4-8
  - JP21 .................................................. 4-9
  - JP22 .................................................. 4-10
  - JP3 .................................................. 4-6
  - JP4 .................................................. 4-6
  - JP5 .................................................. 4-6
  - JP6 .................................................. 4-6, 4-9
  - JP7 and JP8 ....................................... 4-7
  - JP9 and JP10 ...................................... 4-7

**L**

- LEDs .................................................. 4-1, 4-10
  - LED1 .................................................. 2-5, 4-11
  - LED10 .................................................. 4-12
  - LED11 .................................................. 2-5, 4-12
  - LED2 - LED7 ...................................... 3-4, 4-12
| Topic                        | Page Numbers |
|------------------------------|--------------|
| LED3                         | 2-5, 2-15    |
| LED7                         | 2-15         |
| LED8                         | 4-11, 4-12   |
| LED9                         | 4-12         |
| Link Ports                   | 4-5, 4-15    |
| **M**                        |              |
| MCLK                         | 4-6          |
| Memory Map                   | 3-2, 3-3     |
| MIC Pre-Amp                  | 4-7          |
| **P**                        |              |
| PC Configuration             | 2-2          |
| Power Connector              | 4-16         |
| Processor ID                 | 4-8          |
| Programmable Flags           | 4-13         |
| Push Buttons                 | 4-13         |
| Push Buttons ..... 4-10. See also Switches |        |
| **R**                        |              |
| Reset                        | 4-11         |
| Board                        | 4-13         |
| DSP                          | 4-11         |
| Restrictions                 | 3-2          |
| **S**                        |              |
| Sample Frequency             | 4-6          |
| SDRAM                        | 3-2, 3-3, 4-5 |
| SPDIF                        | 4-6          |
| SPI                          | 3-5, 4-3     |
| SPORT0                       | 4-3          |
| SPORT1 and SPORT3            | 4-16         |
| SPORT2                       | 4-3          |
| Switches                     | 4-10         |
| Default Settings             | 2-4          |
| SW1                          | 2-15, 3-4, 4-13 |
| SW2                          | 3-4, 4-13    |
| SW3                          | 3-4, 4-13    |
| SW4                          | 3-4          |
| SW5                          | 3-5          |
| SW6                          | 3-5          |
| SW7                          | 3-5          |
| **U**                        |              |
| UART                         | 4-9          |
| USB                          | 4-14         |
| Monitor LED                  | 4-12         |
| **V**                        |              |
| VERF                         | 3-6          |
| VisualDSP++                  |              |
| Help                         | 1-4          |
| License                      | 2-3, 3-2     |
| Starting                     | 2-16         |
