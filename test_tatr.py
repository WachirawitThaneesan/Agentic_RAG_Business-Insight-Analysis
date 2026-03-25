import sys
try:
    from transformers import AutoImageProcessor, TableTransformerForObjectDetection
    model_name = "microsoft/table-transformer-detection"
    _tatr_processor = AutoImageProcessor.from_pretrained(model_name)
    _tatr_model = TableTransformerForObjectDetection.from_pretrained(model_name)
    print("SUCCESS: TATR loaded successfully.")
except Exception as e:
    print(f"ERROR: {e}")
