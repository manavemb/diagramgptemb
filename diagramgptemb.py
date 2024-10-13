import streamlit as st
from anthropic import Anthropic
from diagrams import Diagram, Cluster
from io import BytesIO, StringIO
import base64
import sys
import traceback
import os
import tempfile
import re

# Import the CLOUD_PROVIDERS dictionary and helper functions
from components import CLOUD_PROVIDERS, generate_import_statements, get_available_components, prepare_llm_context

# Initialize Anthropic client
try:
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
except KeyError:
    st.error("API key for Anthropic is missing. Please add the ANTHROPIC_API_KEY to Streamlit secrets.")
    st.stop()
except Exception as e:
    st.error(f"Failed to initialize Anthropic client: {str(e)}")
    st.stop()

def generate_claude_prompt(user_input, selected_providers, color_scheme, layout_direction):
    llm_context = prepare_llm_context(selected_providers)
    available_components = get_available_components(selected_providers)
    import_statements = generate_import_statements(selected_providers)

    prompt = f"""
Generate Python code using the 'diagrams' library to create a multi-cloud diagram based on the following description:

{user_input}

Use the following import statements:
{import_statements}

Available cloud components and their full import paths:
{llm_context}

The code should:
1. Use the import statements provided above.
2. Only use the available cloud components listed above.
3. Create a Diagram object with show=False and outformat="png".
4. Use appropriate nodes and edges to represent the described cloud architecture.
5. Include any necessary clusters or groupings to represent cloud concepts like VPCs, subnets, or availability zones.
6. Be complete and runnable, assuming the diagrams library is installed.
7. Handle multiple instances of the same component type by creating individual variables (e.g., ec2_1 = EC2("Instance 1"), ec2_2 = EC2("Instance 2")).
8. Use individual >> operators for connections, NOT list-based connections. For example:
   CORRECT:   ec2_1 >> s3
              ec2_2 >> s3
   INCORRECT: [ec2_1, ec2_2] >> s3
9. Use the color scheme: {color_scheme}
10. Use the layout direction: {layout_direction}
11. Only use context managers (with statements) for clusters, such as 'Cluster', and avoid using individual components like VPC or EC2 as context managers.

When using components, call them with their category name, e.g., compute.EC2(), network.VPC(), storage.S3().

IMPORTANT: 
- Your response must contain ONLY valid Python code. 
- Do not include any explanations, comments, or additional text before or after the code. 
- Start with the import statements and end with the Diagram context manager (the 'with' statement). 
- Do not use triple backticks or any other formatting - just pure Python code.
- Ensure all connections are made using individual >> operators, never with lists.
"""
    return prompt

def clean_and_fix_code(code):
    # Remove introductory lines and find start of import statements
    lines = code.split('\n')
    start_index = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('from ') or line.strip().startswith('import '):
            start_index = i
            break
    
    lines = lines[start_index:]
    
    fixed_lines = []
    for line in lines:
        # Ensure only valid context managers are used
        if 'with VPC' in line or 'with ' in line and 'VPC(' in line:
            # Replace with standalone instantiation if VPC is wrongly used in a context manager
            fixed_lines.append(line.replace('with ', '').strip())
        elif '>>' in line and '[' in line and ']' in line:
            # Fix list-based connections
            before, after = line.split('>>')
            left = before.strip().strip('[]').split(',')
            right = after.strip().strip('[]').split(',')
            for l in left:
                for r in right:
                    fixed_lines.append(f"{l.strip()} >> {r.strip()}")
        else:
            fixed_lines.append(line)
    
    return '\n'.join(fixed_lines)

def execute_diagram_code(code):
    with tempfile.TemporaryDirectory() as tmpdirname:
        try:
            filename = os.path.join(tmpdirname, "diagram")
            pattern = r'with Diagram\((.*?)\):'
            match = re.search(pattern, code, re.DOTALL)
            if match:
                args = match.group(1).strip().split(',')
                diagram_name = args[0].strip().strip('"\'"')
                new_args = f'"{diagram_name}", filename="{filename}", show=False, outformat="png"'
                modified_code = code.replace(match.group(0), f'with Diagram({new_args}):')
            else:
                raise ValueError("Could not find Diagram instantiation in the code")

            stdout_capture = StringIO()
            stderr_capture = StringIO()
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture

            try:
                exec(modified_code)
            except Exception as e:
                st.error(f"An error occurred while executing the code: {str(e)}")
                st.error(f"Traceback: {traceback.format_exc()}")
                return None
            finally:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__

            generated_file = f"{filename}.png"
            if os.path.exists(generated_file):
                with open(generated_file, "rb") as f:
                    return BytesIO(f.read())
            else:
                st.error("No PNG file was created.")
                st.error(f"Stdout: {stdout_capture.getvalue()}")
                st.error(f"Stderr: {stderr_capture.getvalue()}")
                return None
        except Exception as e:
            st.error(f"Error executing the code: {str(e)}")
            st.error(f"Traceback: {traceback.format_exc()}")
            return None

def main():
    st.set_page_config(page_title="Multi-Cloud Architecture Diagram Generator", layout="wide")
    st.title("Multi-Cloud Architecture Diagram Generator")

    # Initialize session state
    if 'generated_code' not in st.session_state:
        st.session_state.generated_code = ""
    if 'generated_diagram' not in st.session_state:
        st.session_state.generated_diagram = None

    # Sidebar configuration
    st.sidebar.title("Diagram Configuration")
    diagram_name = st.sidebar.text_input("Enter a name for your diagram:", "my_cloud_diagram")
    color_scheme = st.sidebar.color_picker("Color Scheme", "#3B82F6")  # Default to a nice blue color

    # Model selection and temperature adjustment
    model = st.sidebar.selectbox(
        "Select Claude Model:",
        ["claude-3-opus-20240229", "claude-3-5-sonnet-20240620"],
        index=0
    )
    temperature = st.sidebar.slider("Adjust Temperature:", min_value=0.0, max_value=1.0, value=0.5, step=0.1)

    # Main content area
    col1, col2 = st.columns(2)

    # First row: Cloud Providers and Layout Direction
    with col1:
        st.subheader("Select Cloud Providers")
        selected_providers = st.multiselect(
            "Select Cloud Providers:",
            options=list(CLOUD_PROVIDERS.keys()),
            default=["AWS", "Azure", "GCP"]
        )

    with col2:
        st.subheader("Layout Direction")
        layout_direction = st.selectbox("Layout Direction", ["LR", "TB", "RL", "BT"], index=0)

    st.markdown("---")  # Divider

    # Second row: Describe Architecture and Code Editor
    col3, col4 = st.columns(2)

    with col3:
        st.subheader("Describe Your Architecture")
        user_input = st.text_area(
            "Describe the cloud architecture you want to create:",
            "Example: Create a diagram with an AWS EC2 instance connected to an S3 bucket. Include an Azure Virtual Machine connected to Azure SQL Database. Add a Google Cloud Storage bucket.",
            height=200
        )

        if st.button("Generate Initial Code"):
            with st.spinner("Generating initial cloud diagram code..."):
                try:
                    prompt = generate_claude_prompt(user_input, selected_providers, color_scheme, layout_direction)
                    
                    # Set max_tokens based on the selected model
                    max_tokens = 4000 if model == "claude-3-opus-20240229" else 8192
                    
                    response = client.messages.create(
                        model=model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        messages=[
                            {"role": "user", "content": prompt}
                        ]
                    )
                    generated_code = response.content[0].text.strip()
                    generated_code = clean_and_fix_code(generated_code)  # Clean and fix the generated code
                    st.session_state.generated_code = generated_code
                except Exception as e:
                    st.error(f"An error occurred while generating the initial code: {str(e)}")
                    st.error(f"Traceback: {traceback.format_exc()}")
                    st.session_state.generated_code = ""

    with col4:
        st.subheader("Edit or Write Python Code")
        user_code = st.text_area("Python Code", value=st.session_state.generated_code, height=200, key="user_code")

        if st.button("Generate Diagram"):
            if user_code:
                with st.spinner("Generating diagram from code..."):
                    try:
                        img_bytes = execute_diagram_code(user_code)
                        if img_bytes:
                            st.session_state.generated_diagram = img_bytes
                        else:
                            st.error("Failed to generate the diagram. Please check your code and try again.")
                    except Exception as e:
                        st.error(f"An error occurred while generating the diagram: {str(e)}")
                        st.error(f"Traceback: {traceback.format_exc()}")
            else:
                st.warning("Please enter some Python code to generate the diagram.")

    # Display generated diagram
    st.markdown("---")
    st.subheader("Generated Diagram")
    diagram_placeholder = st.empty()

    if st.session_state.generated_diagram:
        diagram_placeholder.image(st.session_state.generated_diagram.getvalue(), caption="Generated Multi-Cloud Architecture Diagram", use_column_width=True)

        b64 = base64.b64encode(st.session_state.generated_diagram.getvalue()).decode()
        href = f'<a href="data:image/png;base64,{b64}" download="{diagram_name}.png">Download Diagram</a>'
        st.markdown(href, unsafe_allow_html=True)

        export_package = BytesIO()
        export_package.write(b"Diagram:\n")
        export_package.write(st.session_state.generated_diagram.getvalue())
        export_package.write(b"\n\nCode:\n")
        export_package.write(user_code.encode())
        export_package.seek(0)
        st.download_button(
            label="Download Diagram and Code Package",
            data=export_package,
            file_name=f"{diagram_name}_package.txt",
            mime="text/plain"
        )
    else:
        diagram_placeholder.info("No diagram generated yet. Describe your architecture, generate the code, and click 'Generate Diagram' to create one.")

if __name__ == "__main__":
    main()
