# Getting Started with FloSCRIPT – FloTHERM v11.0 

This tutorial is designed to introduce the basic concepts and methodologies involved to develop a task automation utility using FloTHERM v11.0 FloSCRIPT technology and Excel. 

# Table of Contents 

1. Introduction ...... 2   
2. Recorded FloSCRIPT Files . . 2   
2.1. Recorded Actions .... .. 2   
2.2. Recorded FloSCRIPT File Structure .... .. 2   
3. FloSCRIPT Play Back ... .. 4   
3.1. Project\Run FloSCRIPT .. ... 4   
3.2. Command Line FloSCRIPT Play Back . ... 4   
3.3. FloSCRIPT Modifications .. .. 5   
3.4. VBA – Getting Started .. .. 5   
4. Tutorial ... .. 6   
4.1. Record the Baseline FloSCRIPT . .. 6   
4.2. Inspect the Baseline FloSCRIPT . ... 7   
4.3. Getting Starting, Spreadsheet Review .. ... 9   
4.4. Modifying an XML attribute ..... 11 

# 1. Introduction 

FloSCRIPT is a FloTHERM technology designed to facilitate the automation of various modeling tasks. It consists of a XML based list of FloTHERM actions that can be recorded and replayed within the software. As the file format is XML, FloSCRIPT is highly structured, human readable, and thus easily manipulated with any programming language. 

The FloSCRIPT file was introduced in the FloTHERM v10.0 release with support for actions taken in the Project Manager and Drawing Board windows. With the release of v11.0, FloSCRIPT is extended to support automation of the FloMCAD Bridge module, as well as having the capability to initiate play back from a command line and offering full support for solver operations. 

The objective of this document is to describe the first steps a user should follow to begin exploring opportunities with FloSCRIPT, and to illustrate how the installed examples can be used to become productive quickly. 

# 2. Recorded FloSCRIPT Files 

All actions performed by the user in the Project Manager, Drawing Board, and FloMCAD Bridge are automatically recorded to a FloSCRIPT log file. The log files are retained in the following folder in the installation directory: 

.\flosuite_v11\flotherm\WinXP\bin\LogFiles\ 

Note that a maximum of 5 log files are retained at once. Log files can of course be copied to other locations on a computer as needed. Any commands recorded in FloMCAD Bridge will be written to separate log file, as well as to the primary log file for that FloTHERM session. 

Each logfile has a filename that begins with ‘logFile’ and ends with .xml. 

Each logfile specific to FloMCAD Bridge will begin with ‘MCADLogFile’ and end with .xml. 



<table><tr><td rowspan=1 colspan=1> Name</td><td rowspan=1 colspan=1> Date modified</td><td rowspan=1 colspan=1>Type</td><td rowspan=1 colspan=1>Size</td></tr><tr><td rowspan=1 colspan=1>=logFile984532374.xml</td><td rowspan=1 colspan=1>11/12/2014 2:49 PM</td><td rowspan=1 colspan=1> XML Document</td><td rowspan=1 colspan=1>1 KB</td></tr><tr><td rowspan=1 colspan=1>自logFile984522466.xml</td><td rowspan=1 colspan=1>11/12/2014 2:48 PM</td><td rowspan=1 colspan=1> XML Document</td><td rowspan=1 colspan=1>1 KB</td></tr><tr><td rowspan=5 colspan=1>自logFile984516103.xml>logFile984511597.xml logFile984506103.xml□logFile984500341.xml MCADLogFile981087871.xml</td><td rowspan=1 colspan=1>11/12/2014 2:48 PM</td><td rowspan=1 colspan=1> XML Document</td><td rowspan=1 colspan=1>1 KB</td></tr><tr><td rowspan=1 colspan=1>11/12/2014 2:48 PM</td><td rowspan=1 colspan=1> XML Document</td><td rowspan=1 colspan=1>1 KB</td></tr><tr><td rowspan=1 colspan=1>11/12/2014 2:48 PM</td><td rowspan=1 colspan=1> XML Document</td><td rowspan=1 colspan=1>1 KB</td></tr><tr><td rowspan=1 colspan=1>11/12/2014 2:48 PM</td><td rowspan=1 colspan=1> XML Document</td><td rowspan=1 colspan=1>1 KB</td></tr><tr><td rowspan=1 colspan=1>11/12/2014 1:52 PM</td><td rowspan=1 colspan=1> XML Document</td><td rowspan=1 colspan=1>4 KB</td></tr></table>



# 2.1. Recorded Actions 

As the user issues commands in FloTHERM, they are written to the FloSCRIPT log file. Each command is written in a structured way, conforming to the XML format and the FloSCRIPT schema. For example, when a cuboid object is created, the following lines are written to fully describe what the user did, in this case created a cuboid while the Root Assembly was selected: 

<create_geometry geometry _type $=$ "cuboid"> <source_geometry> <geometry name $=$ "Root Assembly"/> </source_geometry>   
</create_geometry> 

If that cuboid were then to be re-sized in the x-direction to $0 . 4 4 ~ \mathsf { m }$ , the FloSCRIPT log file would record: 

<modify_geometry new_value $=$ $=$ "sizex"> <geometry_name> <geometry name ${ } = { }$ "Root Assembly"> <geometry name $=$ "Cuboid" position_in_parent ${ } = { }$ </geometry> </geometry_name>   
</modify_geometry> 

# 2.2. Recorded FloSCRIPT File Structure 

As an XML file format, FloSCRIPT will always be formatted in a structured manner. Using Figure 1 as an example, the following aspects are observed: 

First line, is an XML header. This content is always the same and is used by various file parsers to identify the type of incoming file.   
• Second line, is the first XML element, called xml_log_file. This is the parent XML node for FloSCRIPT, all other nodes are children of it.   
• The lines that begin with ${ < } ! -$ are all XML comments. These do not affect the functionality in any way but are always written out by FloTHERM to describe Copyright data and IP statements. The remainder of the document are XML elements and XML attributes that describe the actions taken, or the actions to be played back. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/f92327e6f68c005e7056a3cefeebb4dd048a263439f5dac70d27df41000d3e3e.jpg)



Figure 1: Example FloSCRIPT File 


It’s important to understand some of the XML terminology in play here, especially when we consider how we need to modify this data for automation applications later. 

An XML element is the basic data descriptor in XML. It can be recognized as text within $< >$ brackets. The first element encountered in Figure 1 is the <xml_log_file> element. Note that all elements must open and close to produce valid XML. The closing form of an XML element has forward slash, ie, $< / \times \mathsf { m l }$ _log_file> is the closing counterpart to <xml_log_file>, and will always be the last line in a FloSCRIPT file. 

XML elements may optionally have one or more XML attributes associated with them. An attribute does not utilize $< >$ brackets, but rather consist of a name and a value, fully contained within an opening XML element. There are many XML attributes in Figure 1, one of which is associated with the <create_geometry> element: 

<create_geometry geometry_type $\mathbf { \equiv }$ ”cuboid”> 

In that line: 

XML Element $=$ create_geometry XML Attribute Name $=$ geometry_type o XML Attribute Value $=$ cuboid 

Note also, there are several instances in Figure 1 where an XML element has two attributes defined for it. 

# 3. FloSCRIPT Play Back 

There are two methods to play back a FloSCRIPT file: interactively within FloTHERM, and on the command line. 

# 3.1. Project\Run FloSCRIPT 

In the Project Manager, use the Project\Run FloSCRIPT (CTRL R) command. This launches a file browser from which the desired FloSCRIPT file can be located and selected. All of the actions in the FloSCRIPT file are then played back in order. 

Solving the model is supported with FloSCRIPT playback. Note that the play back will not proceed until the solver has completed however. The same applies for any lengthy process, such as some of the FloMCAD Bridge commands like ‘Global Simply’, ‘Decompose’ etc. 

In situations where FloSCRIPT causes a user prompt to appear (one example would be if the grid changes for a model that has a set of results), the play back continues after the user interaction. 

# 3.2. Command Line FloSCRIPT Play Back 

FloSCRIPT play back can be initiatedfrom the command line. The appropriate command is: flotherm.bat –f [FloSCRIPT File] 

This command will start FloTHERM, and automatically start play back of the FloSCRIPT file. After this point, the play back is identical to the Project\ Run FloSCRIPT command. 

# 3.3. FloSCRIPT Modifications 

It’s important to note that FloTHERM can replay FloSCRIPT files regardless of origin, provided the file is a well formed XML file and adheres to the FloSCRIPT XML schema. The file does not need to be created by FloTHERM itself. This allows the FloTHERM user to consider automation applications in which either a FloSCRIPT file is created from scratch, or a recorded FloSCRIPT file is used as a baseline, and simply modified as necessary by the user. The latter approach is often easier, as simply driving FloTHERM is a convenient method to create most of the required FloSCRIPT file, and then it’s relatively easy to programmatically modify the XML elements and attributes that require it for that application. 

There are two options for modifying an existing FloSCRIPT file. The first is manual modification which consists of opening the FloSCRIPT file in a text editor, and manually changing XML element values or XML attribute values to suit your purpose. A perfectly valid approach, but generally not a scalable process. The second is to implement a programmatic method to make the modifications. This requires more resource and effort up front to develop the method, but is also extremely scalable as expertise is built up. The primary focus of this document is to illustrate how a popular engineering spreadsheet tool can be used to quickly build up FloSCRIPT modifying macro using Excel’s VBA programming environment. 

# 3.4. VBA – Getting Started 

The Visual Basic for Applications (VBA) environment available in Excel is commonly used across industries to automate many tasks. Typically not active by default, it can be made visible in the Options – Customize Ribbon window, by checking the ‘Developer’ option. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/3e4cc8f94a46d67466e64da181d0d54af91626447fb62d7e53baa4fa73c09fe5.jpg)


After which a Developer tab becomes available on the main toolbar. Once the Developer tab is available, you can click on the Visual Basic button to enter the environment. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/d723cad2f175139cf373f2d462f4d7f2abf3be67305cf67a16a0b83f2a102739.jpg)


![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/2b0561ec61980915205c567a3667d55c3cfb1a2ae6dca739212c44008f8ba026.jpg)


The intention of this document is not to instruct on the capabilities of VBA or programming techniques in general, but rather to demonstrate how the utilities provided with a FloTHERM installation can be used as a template to develop your own applications. The ‘FloSCRIPT-Getting-Started.xlsm’ file that is provided in the .\flosuite_v11\flotherm\examples\FloSCRIPT\Tutorial folder includes several simple functions that allow you to quickly search for an element inside a FloSCRIPT, and then modify XML attribute values as needed. The functions are written in such a way that you do not need to know the details thoroughly, but you should be comfortable with the concepts of XML elements and XML attributes described earlier in this document. 

To begin, we’ll use this spreadsheet example as a starting point to create a simple application in the next section. 

# 4. Tutorial 

The tutorial exercise will show you how to: 

Record a FloSCRIPT file that creates a cuboid, renames it, and re-sizes it in the X-direction. Create a VBA macro to modify the FloSCRIPT file to change the cuboid name and the X dimension. • Create a VBA macro to run the modified FloSCRIPT file on the command line. 

# 4.1. Record the Baseline FloSCRIPT 

Steps: 

. Start a new FloTHERM session. Select the Root Assembly • Create a new cuboid object 

. Change the X-Size of the cuboid to $0 . 4 4 ~ \mathsf { m }$ • Change the name of the cuboid to “Mentor” Close FloTHERM without saving the model. 

Now create a new folder to store the FloSCRIPTS we’ll use in this tutorial. Create a new folder called c:\macros. 

Next, go to the .\flosuite_v11\flotherm\WinXP\bin\LogFiles\ folder and identify the FloSCRIPT file you just recorded (hint, sort by ‘Date Modified’ in Windows Explorer). Copy this file and paste it in c:\macros. 

Rename the recorded FloSCRIPT file as ‘first-macro.xml’ 

# 4.2. Inspect the Baseline FloSCRIPT 

Before we begin to modify the FloSCRIPT, it’s crucial to understand what XML elements and attributes need to be changed. Open ‘first-macro.xml’ in a text editor (ie, Notepad, or Notepad $^ { + + }$ ). 

Identify the lines that were recorded to set the cuboid X-size as $0 . 4 4 ~ \mathsf { m }$ . It should look like this: 

<geometry_name> $=$ "Root Assembly"> $=$ 

The element is ‘modify_geometry’ and it has two attributes defined: 

new_value $= " 0 . 4 4 "$ . property_name $= ^ { \overrightarrow { } }$ ”sizeX” 

To modify the x-size value that is used during FloSCRIPT playback, we need a method to change the 0.44 value for the ‘new_value’ attribute. 

Now, identify the lines that were recorded to change the cuboid name to “Mentor”. It should look like this: 

<modify_geometry new_value $=$ "Mentor" property_name="name"> <geometry_name> <geometry name $=$ "Root Assembly"> <geometry name $=$ "Cuboid" position_in_parent="0"/> </geometry> </geometry_name>   
</modify_geometry> 

Again, the element is ‘modify_geometry’, and again there are two attributes: 

new_value $= ^ { \ ' }$ ”Mentor” . property_name $=$ ”name” 

To modify the cuboid name that is used during FloSCRIPT playback, we will need a method to change the “Mentor” value for the ‘new_value’ attribute. 

Identifying what elements and attributes need modifying is always an important step when developing FloSCRIPT automation utilities. In the next stage of the tutorial, we’ll use VBA in Excel to make these changes. 

Before moving on however, scroll to the bottom of the file and note that the software ‘quit’ command has been recorded. For the tutorials, we want FloTHERM to stay open after FloSCRIPT playback completes to facilitate output inspection so we do not need this line. Delete that line, and then save the file. 



> FloSCRIPT macro files are XML. Opening one in a text editor shows `<project_save_as>`, `<select_geometry>`, `<create_geometry>`, `<modify_geometry>` elements wrapped in an `<xml_log_file>` envelope — the same high-level operations seen in the GUI macro recorder.



# 4.3. Getting Starting, Spreadsheet Review 

First, copy the ‘FloSCRIPT-Getting-Starting.xlsm’ spreadsheet into the c:\macros folder. The ‘FloSCRIPT-Getting-Started.xlsm’ file that is provided in the .\flosuite_v11\flotherm\examples\FloSCRIPT\Tutorial folder . Rename the spreadsheet as ‘First-FloSCRIPT-Project.xlsm’, and then open it. Note that the spreadsheet contains Excel VBA macros and as a result has the .xlsm extension. To enable the macros click the “Enable Content” button in the SECURITY WARNING Banner. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/498ab8bb31235fa3bd5f0a0da4fddf350db5dca67950d443438bf001764f2e5d.jpg)



H 


There are several spreadsheet cells with information defined. We’ll modify this data later in the tutorial. Now, go to the Developer tab in the toolbar, and click the Visual Basic button to enter the VBA environment. 

There are three modules pre-defined in this spreadsheet: 

Example Module: This is the module that holds the main controlling subroutine that opens, saves, and (eventually) modifies a FloSCRIPT file. • FloSCRIPT: This is the module that contains subroutines that allow you to: o Modify a specified XML attribute o Play back a FloSCRIPT file in FloTHERM from the command line o Solve a specified FloTHERM model on the command line. General: This module contains subroutines that support basic file system operations, like changing the FloTHERM installation folder, checking for the existence of a file prior to opening it, etc. 

We’ll start with the ‘Example Module’. Double-Click it to reveal the macro contents on the right side of the screen. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/6e6cbf4a7068a6e3382c352cf99754b064cc32adddaa791d87e4cbb82388de2c.jpg)


This program is very simple at the moment. All it does it load a FloSCRIPT file, and save it with a new name. A brief description of each section of the code is shown in the table below. 



<table><tr><td rowspan=1 colspan=1>VBA Code</td><td rowspan=1 colspan=1> Explanation</td></tr><tr><td rowspan=1 colspan=1>Dim myPath As String, myFile As String, mynewFile AsString, flotherm_path As String</td><td rowspan=2 colspan=1> Declare string variables and xmldoc as an object to bedefined later</td></tr><tr><td rowspan=1 colspan=1>Dim xmldoc As Object</td></tr><tr><td rowspan=1 colspan=1>Set xmldoc = CreateObject("MSXML.DOMDocument")</td><td rowspan=1 colspan=1> Set xmldoc as a xml document allowing for using ofthe XML DOM (Document Object Model)</td></tr><tr><td rowspan=1 colspan=1>myPath = CStr(Sheet1.Cells(2, 2))</td><td rowspan=4 colspan=1>Retrieve path and file names (converted to string:CStr) from worksheet and set them equal to previouslydeclared string variables</td></tr><tr><td rowspan=1 colspan=1>myFile = CStr(Sheet1.Cells(3, 2))</td></tr><tr><td rowspan=1 colspan=1>mynewFile = CStr(Sheet1.Cells(4, 2))</td></tr><tr><td rowspan=1 colspan=1>flotherm_path = Sheet1.Cells(3,8).value</td></tr><tr><td rowspan=1 colspan=1> xmldoc.Load myPath & myFile</td><td rowspan=1 colspan=1>Open the XML FloSCRIPT file which is referenced asxmldoc</td></tr><tr><td rowspan=1 colspan=1> xmldoc.Save myPath & mynewFile</td><td rowspan=1 colspan=1>Save the XML FloSCRIPT file to the new file name(mynewFile)</td></tr></table>



Note that four items are read from the spreadsheet cells and used in the macro. Back in the spreadsheet make sure you understand the data that is being read. Note that the FloTHERM path will be needed when the FloSCRIPT file is played from the command line. 

To have the program do something useful, we need to ensure that the spreadsheet data being read matches the files we have produced so far, specifically: 

· Path to the Baseline FloSCRIPT file needs to be c:\macros\ Baseline FloSCRIPT: first-macro.xml • New FloSCRIPT File: New-FloSCRIPT.xml 

Make those changes (if necessary) by clicking on the excel icon in the upper left and then go back to VBA. Click the ‘Run/Sub User Form’ icon to play the active macro. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/a05dcc0e9df4bb60ebf9905bfcee9e435f19bde9feddac97171b6f70a3c729e1.jpg)


There should be a new .xml file in c:\macros now, called “New-FloSCRIPT.xml”. Start FloTHERM and playback that file and confirm that the outcome meets expectations. Close FloTHERM. 

# 4.4. Modifying an XML attribute 

The provided ‘FloSCRIPT’ module in VBA contains a subroutine that will modify the value of an existing XML attribute when called. The name of the subroutine is ‘modify_att’ and has the following inputs: 

xmldoc [A reference to the FloSCRIPT XML file that was previously opened]   
• Element name [the name of the element containing the target attribute]   
• Attribute name [the name of the attribute that is be modified]   
• Attribute value [the EXISTING value of that attribute]   
• New Attribute value [the DESIRED value of that attribute] Which_one [OPTIONAL: in the event of multiple elements and attributes that match the above criteria, the subroutine will apply the new attribute value for all matching attributes. If this is not the intent, the which_one field can be used to specify which of the matches should be modified by providing an index value…1 being the first match found from the top of the file, 2 being the second, etc.) 

To use this subroutine, the subroutine call is: 

Call modify_att(xmldoc, element, attribute_name, attribute_value, new_attribute_value) 

In the case of modifying the cuboid x-size to a different value, the baseline FloSCRIPT is: 

$=$ <geometry_name> $=$ "Root Assembly"> $=$ 

And thus the appropriate way to modify the size (to $0 . 5 5 ~ \mathsf { m }$ ) to with this subroutine is: 

Call modify_att(xmldoc, "modify_geometry", "new_value", "0.44", "0.55") 

To change the cuboid name (to ‘Mentor Graphics’) the subroutine call would look like: 

Call modify_att(xmldoc, "modify_geometry", "new_value", "Mentor", "Mentor Graphics") 

# 4.5. Modifying an Attribute with Excel VBA with FloSCRIPT 

There are a number of subroutines associated with this spreadsheet but only two are designed to be interacted with directly by the user. The two subroutines are: 

Example (located in the ‘Example_Module’ module): Main subroutine that will load, modify, and save the FloSCRIPT XML file   
• browseForInstall (located in the ‘General’ module): Subroutine that allows the user to navigate to the Flosuite directory and write the path to the worksheet 

The macros can be accessed from the worksheet on the DEVELOPER tab as shown below. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/c530d8584995d967d334f8774e10da37466b609ad3dde1ea8369b3283dac1e83.jpg)



H 2 


Select the “example” macro and click “Edit”. 

In the “example” subroutine add the two subroutine calls for modifying the “SizeX” and the name attributes after the code that loads the FloSCRIPT file, shown in the image below. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/1530197b68af5a3d53abcccfd04855122694c6fb6953dda4946574742e49829f.jpg)


After the subroutines have been added the code should look like this: 

xmldoc.Load myPath & myFile Call modify_att(xmldoc, "modify_geometry", "new_value","0.44","0.55") Call modify_att(xmldoc, "modify_geometry", "new_value", "Mentor", "Mentor Graphics") 

To have FloTHERM launch and run the FloSCRIPT from the command line we will call the “play_floscript” subroutine. Note that we will make use of the variables: “myPath”, “mynewFile”, and “flotherm_path”. The “example” macro retrieves the cell values from the worksheet and stores them under these variable names. The new code will be added after the FloSCRIPT file is saved with the new file name. The updated code should look like this: 

xmldoc.Load myPath & myFile Call modify_att(xmldoc, "modify_geometry", "new_value", "0.44", "0.55") Call modify_att(xmldoc, "modify_geometry", "new_value", "Mentor", "Mentor Graphics") 

xmldoc.Save myPath & mynewFile Call play_floscript (myPath, mynewFile, flotherm_path) 

# End Sub 

# Try running the macro from the Run menu as shown: 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/3167663af3cd167c4e98950858be0cc5ab342a5d3241837c60d4830f881b6566.jpg)


If successful FloTHERM should launch and play the FloSCRIPT file that creates a cuboid that is named “Mentor Graphics” and has a Size X of $0 . 5 5 ~ \mathsf { m }$ . 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/906e8295c98ee7826f5c40dd8ed8383559efc83d02a2cfc33b756e6a354735f1.jpg)


# 4.6. Putting it All Together 

Another method to access the macros would be to link them to a button or text box. This is convenient if the spreadsheet will be shared with other users or reused many times. Update our spreadsheet to have two text boxes linked to the two macros. 

Under the INSERT ribbon toolbar choose expand the Shapes menu to select the Text Box. Sketch one text box for each macro. Add text to the textboxes: “Create and Play FloSCRIPT” and “Update Path” 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/2711d6be0ba8e7003538388c331aca8194a5bd0553fea7ca09fba793398cbffc.jpg)


![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/8d2a1488e794ad37a1364bcec9397b25581acc529b00fd8de984882a016bdc8a.jpg)


The text box fill and outline colors can be added to distinguish them from the rest of the worksheet if desired. To assign a macro to a text box you first select the text box and right click. Choose Assign Macro from the options and select the associated macro. In this example the macro “browseForInstall” is associated with the text box with the text “Update Path”. The text box with “Create and Play FloSCRIPT” is associated with the macro named “example”. 

![image](https://cdn-mineru.openxlab.org.cn/result/2026-04-02/9b2ef03c-7029-4d72-b496-0012ceeefc0b/c4847c8c5a06be7d247cb683b986f907575e1a1b3f3933c1b8e0cbe82b3d666c.jpg)


Now let’s update the functionality and accessibility of the “example” macro. Rather than changing the values in the function directly, as we’ve done so far, we’ll link variables to excel cells which will greatly increase the ease of use. 

Let’s start by formatting some cells in the worksheet for user input for both the current values and the new Attribute values. Note that the input cells column is “B” or the $2 ^ { \mathsf { n d } }$ column, and the rows range from 7 to 10. 



<table><tr><td></td><td>A</td><td>B</td><td>C</td><td></td></tr><tr><td>1</td><td rowspan="4">Path to Baseline FloSCRIPT Baseline FloSCRIPT New FloSCRIPT Name New-FloSCRIPT.xml</td><td rowspan="4">c:\macros\ first-macro.xml</td><td rowspan="4"></td></tr><tr><td>2</td></tr><tr><td>3 4</td></tr><tr><td>5</td></tr><tr><td>6 User Inputs</td><td rowspan="5">Current Attribute Value: 0.44 New Attribute Value: 0.55 Current Attribute Value: Mentor</td><td rowspan="5">Cuboid X-size [m] Cuboid</td></tr><tr><td>7</td></tr><tr><td>8</td></tr><tr><td>9</td></tr><tr><td></td></tr><tr><td>10 11</td><td>New Attribute Value: Mentor Graphics</td><td></td><td> Name</td></tr></table>



We now need to modify the “example” subroutine. Launch the Excel VBA window from the DEVELOPER tab by clicking Visual Basic OR type Alt-F11 on the keyboard. 

The updates required to the subroutine include: 

Dimension 4 new variables for the current and new values of the attributes. The “name” variables will be declared as strings and the “size” variable as double (double precision).   
Set the new variables equal to the cell values from the worksheet   
• Modify the “modify_att” subroutines to reference the new variables 

An example of the updated subroutine is shown below, with the new and modfied lines highlighted in yellow. 

# Public Sub example () 

Dim myPath As String, myFile As String, mynewFile As String, flotherm_path A Dim xmldoc As Object 

Set xmldoc $=$ CreateObject ("MsxML . DOMDocument ") 

myPath $=$ CStr(Sheet1.Cells(2, 2)) myFile $=$ CStr(Sheet1.Cells(3, 2)) mynewFile $=$ CStr(Sheet1.Cells(4, 2)) flotherm_path $=$ Sheet1.Cells (3, 8) .Value 

'Read geometry data from spreadsheet $\approx$ $\approx$ $$ $\approx$ 

# 'Open the FloSCRIPT file 

xmldoc.Load myPath & myFile 

'Save it with a new name xmldoc.Save myPath & mynewFile 

Call play_floscript (myPath, mynewFile, flotherm_path) 

# End Sub 

After editing the subroutine return to the worksheet and click the ‘Create and Play FloSCRIPT’ text box to run the subroutine. If successful the following should occur: 

• FloTHERM launches   
• A cuboid with a default name and size is created in the Root Assembly   
• The cuboid size and then name are updated 

With this in place you can update the ‘new’ values of X-size and name in the spreadsheet cells and re-run the macro as many times as you want. While this example is very simple, you can use the workflow outlined in this tutorial as foundation for FloSCRIPT automation utilities of any complexity. 

# 5. Summary 

An introduction to FloSCRIPT, a FloTHERM technology designed to facilitate the automation of various modeling tasks, has been presented. The intention was not to instruct on the capabilities of VBA or programming techniques in general, but rather to demonstrate how the utilities provided with a FloTHERM installation can be used as a template to develop your own automation applications. 

The work flow to development such automation applications is always the same: 

• Create a baseline FloSCRIPT file simply by using FloTHERM to perform the basic modeling steps. • Open the recorded baseline FloSCRIPT and identify which XML attributes need to modified. • Use the provided VBA examples to programmatically modify these attributes with spreadsheet data • Initiate FloSCRIPT play back from Excel 

Applications in which FloSCRIPT automation will lead to significant productivity gains include: 

Repetitive simulations o To accelerate your own daily simulation activities, e.g. package characterization o To support the field, simulation as a ‘value add’ to the sales process   
• ‘One touch’ investigations of thermal compliance in a range of customer operating environments   
• Automatically simulate more advanced control strategies o Thermostatic power control, fan derating, etc.   
• Ensure all team members can get consistently good results o Capture and enforce ‘best modeling practice’   
Integrate thermal analysis into a wider multi-disciplinary design environment 

Additional automation examples are included as part of the FloTHERM installation at: …\flosuite_v11\flotherm\examples 