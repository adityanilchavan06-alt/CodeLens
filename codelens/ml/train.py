"""Fine-tune CodeT5 from prepared CodeLens JSONL examples."""

import argparse
from datasets import load_dataset
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="JSONL output created by prepare_data.py.")
    parser.add_argument("--output", default="trained-codet5", help="Directory for the fine-tuned model.")
    parser.add_argument("--base-model", default="Salesforce/codet5-small")
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    arguments = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(arguments.base_model)
    model = AutoModelForSeq2SeqLM.from_pretrained(arguments.base_model)
    dataset = load_dataset("json", data_files=arguments.data, split="train")

    def tokenize_batch(batch):
        model_inputs = tokenizer(batch["input"], max_length=1024, truncation=True)
        targets = tokenizer(text_target=batch["target"], max_length=512, truncation=True)
        model_inputs["labels"] = targets["input_ids"]
        return model_inputs

    tokenized = dataset.map(tokenize_batch, batched=True, remove_columns=dataset.column_names)
    training_args = Seq2SeqTrainingArguments(
        output_dir=arguments.output,
        num_train_epochs=arguments.epochs,
        per_device_train_batch_size=arguments.batch_size,
        learning_rate=5e-5,
        save_strategy="epoch",
        predict_with_generate=True,
        report_to="none",
    )
    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model),
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(arguments.output)
    tokenizer.save_pretrained(arguments.output)
    print(f"Saved the fine-tuned model to {arguments.output}.")


if __name__ == "__main__":
    main()
