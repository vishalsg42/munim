# Why Bedrock returned INVALID_PAYMENT_INSTRUMENT on my Indian AWS account

*Draft for builder.aws.com, post 1 of 3*

I spent an hour of a hackathon deadline on an error whose cause was sitting in the
API response the whole time. Writing it down because the fix is not obvious and
the error message points somewhere misleading.

## The symptom

Every Anthropic model on Bedrock, in `us-east-1`, on a fresh account with
`AdministratorAccess`:

```
AccessDeniedException: Model access is denied due to INVALID_PAYMENT_INSTRUMENT:
A valid payment instrument must be provided. Your AWS Marketplace subscription
for this model cannot be completed at this time.
```

Payment Preferences showed UPI AutoPay, enabled, set as default, green tick. The
account had a valid payment method by every indication the console gives you.

## What it was not

Three plausible causes, each eliminated:

**Not IAM.** The user had `AdministratorAccess`. `bedrock:ListFoundationModels`
worked and returned every Claude model; only `Converse` failed.

**Not the Anthropic use-case form.** First-time users of Anthropic models on
Bedrock must submit one, and until you do the error is different:
`ResourceNotFoundException: Model use case details have not been submitted`.
Submitting it changed the error, which is how I knew that gate had cleared.

**Not propagation.** The message says to retry after two minutes. I polled for
twenty. It never changed.

## What it actually was

Bedrock model access is provisioned as an **AWS Marketplace subscription** with
contract pricing. And since March 2022, **AWS Marketplace does not support
stored credit or debit cards for AISPL customers**, Amazon Internet Services
Private Limited, the entity Indian AWS accounts are billed through, because of
RBI regulation on card-data storage by payment aggregators.

UPI AutoPay covers your regular AWS invoices. It does not satisfy the Marketplace
subscription. So the console is telling the truth when it says your payment
method is fine, and Bedrock is telling the truth when it says it isn't. They are
talking about different things.

The fix is a support case asking for the Marketplace payment instrument to be
updated or Pay By Invoice enabled. Account and Billing cases are free on Basic
support.

## The part worth keeping

I nearly missed the cause because my own diagnostic hid it. The probe printed:

```python
except ClientError as e:
    print(f"{e.response['Error']['Code']}: {e.response['Error']['Message'][:95]}")
```

`INVALID_PAYMENT_INSTRUMENT` appears about 40 characters into a message I was
truncating at 95, visible, and not looked at, because a background poller was
printing only `e.response['Error']['Code']`. I concluded "propagation, wait
fifteen minutes" from an error that named its own cause.

**Never truncate an error message in a diagnostic.** The bytes cost nothing and
the alternative is an hour of confident wrong theories.

## And a note on not being blocked by it

The hackathon required the Strands Agents SDK, not Bedrock. Strands is model
portable by design, so the whole thing moved to a different host with one
environment variable and no code change:

```python
def build_model():
    try:
        from strands.models.bedrock import BedrockModel
        return BedrockModel(model_id=BEDROCK_MODEL, region_name=region)
    except Exception:
        pass
    from strands.models.gemini import GeminiModel
    return GeminiModel(model_id="gemini-2.5-flash")
```

That portability is advertised. It is more convincing having exercised it under
duress than having read about it.
